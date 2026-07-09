"""FastAPI backend — WebSocket chat + PDF file watcher."""

import asyncio
import contextlib
import json
import os
import time
import typing as t
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from watchfiles import awatch

from dreadnode.agent.events import (
    AgentEnd,
    AgentError,
    AgentEvent,
    AgentStart,
    AgentStalled,
    GenerationEnd,
    Reacted,
    StepStart,
    ToolEnd,
    ToolStart,
)
from dreadnode.agent.reactions import Fail, Finish, RetryWithFeedback

from .agent import create_agent

# ---------------------------------------------------------------------------
# Module-level configuration (set once via ``configure()`` before server start)
# ---------------------------------------------------------------------------

_paper_dir: str = ""
_model: str = ""
_api_key_env: str | None = None
_search_api_key_env: str | None = None

# WebSocket clients subscribed to PDF change notifications.
_pdf_clients: set[WebSocket] = set()


def configure(
    paper_dir: str,
    model: str,
    api_key_env: str | None = None,
    search_api_key_env: str | None = None,
) -> None:
    """Store runtime configuration for the server.

    Must be called before ``uvicorn.run(app, ...)``.

    Args:
        paper_dir: Absolute path to the paper working directory.
        model: LLM model identifier forwarded to the agent.
        api_key_env: Name of the env-var holding the LLM API key (optional).
        search_api_key_env: Name of the env-var holding the Tavily search
            API key (optional).
    """
    global _paper_dir, _model, _api_key_env, _search_api_key_env
    _paper_dir = os.path.abspath(paper_dir)
    _model = model
    _api_key_env = api_key_env
    _search_api_key_env = search_api_key_env


# ---------------------------------------------------------------------------
# PDF file watcher
# ---------------------------------------------------------------------------

async def _watch_pdf() -> None:
    """Watch ``build/main.pdf`` for changes and notify connected WebSocket clients."""
    watch_dir = os.path.join(_paper_dir, "build")

    if not os.path.isdir(watch_dir):
        os.makedirs(watch_dir, exist_ok=True)

    async for changes in awatch(watch_dir):
        for _change_type, changed_path in changes:
            if not changed_path.endswith("main.pdf"):
                continue
            msg = json.dumps({"type": "pdf_updated", "timestamp": time.time()})
            disconnected: set[WebSocket] = set()
            for ws in _pdf_clients:
                try:
                    await ws.send_text(msg)
                except Exception:
                    disconnected.add(ws)
            _pdf_clients -= disconnected


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> t.AsyncIterator[None]:
    """Start the PDF watcher on server boot, cancel on shutdown."""
    task = asyncio.create_task(_watch_pdf())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=_lifespan)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def get_config() -> dict[str, t.Any]:
    """Return the current server configuration (paper dir, model)."""
    return {
        "paper_dir": _paper_dir,
        "model": _model,
    }


@app.get("/api/pdf", response_model=None)
async def get_pdf() -> FileResponse | JSONResponse:
    """Serve the latest built PDF, or 404 if it doesn't exist yet."""
    pdf_path = os.path.join(_paper_dir, "build", "main.pdf")
    if not os.path.exists(pdf_path):
        return JSONResponse({"error": "PDF not found"}, status_code=404)
    return FileResponse(pdf_path, media_type="application/pdf")


# ---------------------------------------------------------------------------
# WebSocket: PDF update notifications
# ---------------------------------------------------------------------------

@app.websocket("/ws/pdf")
async def ws_pdf(websocket: WebSocket) -> None:
    """Keep-alive WebSocket that pushes ``pdf_updated`` events to the client."""
    await websocket.accept()
    _pdf_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _pdf_clients.discard(websocket)


# ---------------------------------------------------------------------------
# WebSocket: Chat agent
# ---------------------------------------------------------------------------

def _format_event(event: AgentEvent) -> dict[str, t.Any] | None:
    """Convert a dreadnode ``AgentEvent`` to a JSON-serializable dict for the frontend.

    Returns ``None`` for event types that should not be forwarded.
    """
    if isinstance(event, AgentStart):
        return {"type": "agent_start", "agent": event.agent.name}

    if isinstance(event, StepStart):
        return {"type": "step_start", "step": event.step}

    if isinstance(event, GenerationEnd):
        content = event.message.content if event.message.content else ""
        usage = None
        if event.usage:
            usage = {
                "input_tokens": event.usage.input_tokens,
                "output_tokens": event.usage.output_tokens,
                "total_tokens": event.usage.total_tokens,
            }
        return {
            "type": "generation",
            "content": content,
            "role": event.message.role,
            "usage": usage,
        }

    if isinstance(event, ToolStart):
        return {
            "type": "tool_start",
            "tool": event.tool_call.name,
            "args": event.tool_call.function.arguments,
        }

    if isinstance(event, ToolEnd):
        content = event.message.content if event.message.content else ""
        return {
            "type": "tool_end",
            "tool": event.tool_call.name,
            "result": content[:2000],
            "stop": event.stop,
        }

    if isinstance(event, AgentError):
        return {"type": "error", "message": str(event.error)}

    if isinstance(event, AgentStalled):
        return {"type": "stalled"}

    if isinstance(event, Reacted):
        reaction = event.reaction
        reaction_name = type(reaction).__name__
        detail = ""
        if isinstance(reaction, RetryWithFeedback):
            detail = f": {reaction.feedback}"
        elif isinstance(reaction, Fail):
            detail = f": {reaction.error}"
        elif isinstance(reaction, Finish) and reaction.reason:
            detail = f": {reaction.reason}"
        return {
            "type": "reacted",
            "content": f"Hook '{event.hook_name}' reacted with {reaction_name}{detail}",
        }

    if isinstance(event, AgentEnd):
        return {
            "type": "agent_end",
            "stop_reason": event.stop_reason,
            "failed": event.result.failed,
            "steps": event.result.steps,
            "usage": {
                "input_tokens": event.result.usage.input_tokens,
                "output_tokens": event.result.usage.output_tokens,
                "total_tokens": event.result.usage.total_tokens,
            },
        }

    return None


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Per-connection chat session: creates an agent and streams events back.

    The agent runs in a separate ``asyncio.Task``.  The message loop races
    ``websocket.receive_text()`` against the agent task so it can handle
    ``{"type": "cancel"}`` messages while the agent is working.
    """
    await websocket.accept()

    agent = create_agent(_model, _paper_dir, _api_key_env, _search_api_key_env)
    agent_task: asyncio.Task[None] | None = None

    async def _run_agent(user_input: str) -> None:
        """Stream agent events to the WebSocket. Runs inside a cancellable task."""
        try:
            async with agent.stream(user_input) as events:
                async for event in events:
                    formatted = _format_event(event)
                    if formatted:
                        await websocket.send_text(json.dumps(formatted))
        except asyncio.CancelledError:
            await websocket.send_text(json.dumps({
                "type": "agent_end",
                "stop_reason": "cancelled",
                "failed": True,
                "steps": 0,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            }))
        except WebSocketDisconnect:
            raise
        except Exception as exc:
            try:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Agent error: {exc}",
                }))
            except WebSocketDisconnect:
                raise

    async def _cancel_agent() -> None:
        """Cancel the running agent task and wait for cleanup."""
        nonlocal agent_task
        if agent_task and not agent_task.done():
            agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await agent_task
        agent_task = None

    async def _recv_message() -> str:
        """Receive a WebSocket message, racing against the agent task if active.

        While the agent is running, this waits for whichever completes first:
        the next WebSocket message or the agent task finishing.  If the agent
        finishes first, loops back to a plain receive.
        """
        nonlocal agent_task
        while True:
            if not agent_task or agent_task.done():
                # No agent running — if the previous task raised, propagate
                if agent_task and agent_task.done() and not agent_task.cancelled():
                    exc = agent_task.exception()
                    if exc:
                        raise exc
                agent_task = None
                return await websocket.receive_text()

            # Agent running — race recv vs agent completion
            recv_task: asyncio.Task[str] = asyncio.create_task(websocket.receive_text())
            done, _ = await asyncio.wait(
                [agent_task, recv_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if recv_task in done:
                return recv_task.result()

            # Agent finished first — cancel the pending recv and loop
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recv_task

    try:
        while True:
            data: str = await _recv_message()

            try:
                msg: dict[str, t.Any] = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON received",
                }))
                continue

            msg_type: str = msg.get("type", "message")

            # --- Cancel ---
            if msg_type == "cancel":
                await _cancel_agent()
                continue

            # --- User message ---
            user_input: str = msg.get("content", "")
            if not user_input.strip():
                continue

            # Cancel any prior run before starting a new one
            await _cancel_agent()
            agent_task = asyncio.create_task(_run_agent(user_input))

    except WebSocketDisconnect:
        await _cancel_agent()


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

def mount_frontend(frontend_dist: str) -> None:
    """Mount the built frontend as static files on ``/``.

    Args:
        frontend_dist: Path to the Vite ``dist/`` directory.
    """
    if os.path.isdir(frontend_dist):
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
