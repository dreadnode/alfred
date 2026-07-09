"""FastAPI backend — WebSocket chat + PDF file watcher."""

import asyncio
import contextlib
import json
import os
import time
import typing as t
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

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

if t.TYPE_CHECKING:
    from dreadnode.agent import TaskAgent

# ---------------------------------------------------------------------------
# Module-level configuration (set once via ``configure()`` before server start)
# ---------------------------------------------------------------------------

_paper_dir: str = ""
_model: str = ""
_api_key_env: str | None = None
_search_api_key_env: str | None = None

# WebSocket clients subscribed to PDF change notifications.
_pdf_clients: set[WebSocket] = set()

_SESSION_TTL: float = 3600.0  # 1 hour — sessions idle longer than this are pruned


@dataclass
class _Session:
    """In-memory chat session: holds the agent and its event history."""

    session_id: str
    agent: "TaskAgent"
    history: list[dict[str, t.Any]] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)


# Active sessions keyed by session ID.  Kept alive across WebSocket reconnects.
_sessions: dict[str, _Session] = {}


def _prune_sessions() -> None:
    """Remove sessions that have been idle longer than ``_SESSION_TTL``."""
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s.last_active > _SESSION_TTL]
    for sid in expired:
        del _sessions[sid]


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
    """Per-connection chat session with reconnect support.

    On first connect the server creates a new session (agent + event history)
    and sends ``session_start`` with the session ID.  On reconnect the client
    sends ``{"type": "resume", "session_id": "..."}`` and the server replays
    the stored event history, then reattaches to the existing agent.

    The agent runs in a separate ``asyncio.Task`` so the message loop can
    receive ``cancel`` messages concurrently.
    """
    await websocket.accept()

    session: _Session | None = None
    agent_task: asyncio.Task[None] | None = None

    def _get_or_create_session(session_id: str | None) -> _Session:
        """Look up an existing session or create a new one.

        Prunes expired sessions on each call and updates ``last_active``.
        """
        _prune_sessions()
        if session_id and session_id in _sessions:
            _sessions[session_id].last_active = time.time()
            return _sessions[session_id]
        new_id = str(uuid.uuid4())
        new_session = _Session(
            session_id=new_id,
            agent=create_agent(_model, _paper_dir, _api_key_env, _search_api_key_env),
        )
        _sessions[new_id] = new_session
        return new_session

    async def _send_event(event_dict: dict[str, t.Any]) -> None:
        """Send a formatted event to the client and record it in session history."""
        if session:
            session.history.append(event_dict)
        await websocket.send_text(json.dumps(event_dict))

    async def _run_agent(user_input: str) -> None:
        """Stream agent events to the WebSocket. Runs inside a cancellable task."""
        assert session is not None
        session.last_active = time.time()
        user_event: dict[str, t.Any] = {"type": "user_message", "content": user_input}
        session.history.append(user_event)
        try:
            async with session.agent.stream(user_input) as events:
                async for event in events:
                    formatted = _format_event(event)
                    if formatted:
                        await _send_event(formatted)
        except asyncio.CancelledError:
            try:
                await _send_event({
                    "type": "agent_end",
                    "stop_reason": "cancelled",
                    "failed": True,
                    "steps": 0,
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                })
            except WebSocketDisconnect:
                pass  # Client already gone — event is still recorded in history
        except WebSocketDisconnect:
            raise
        except Exception as exc:
            try:
                await _send_event({
                    "type": "error",
                    "message": f"Agent error: {exc}",
                })
            except WebSocketDisconnect:
                raise

    async def _cancel_agent() -> None:
        """Cancel the running agent task and wait for cleanup."""
        nonlocal agent_task
        if agent_task and not agent_task.done():
            agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await agent_task
        agent_task = None

    async def _recv_message() -> str:
        """Receive a WebSocket message, racing against the agent task if active."""
        nonlocal agent_task
        while True:
            if not agent_task or agent_task.done():
                if agent_task and agent_task.done() and not agent_task.cancelled():
                    exc = agent_task.exception()
                    if exc:
                        raise exc
                agent_task = None
                return await websocket.receive_text()

            recv_task: asyncio.Task[str] = asyncio.create_task(websocket.receive_text())
            done, _ = await asyncio.wait(
                [agent_task, recv_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if recv_task in done:
                return recv_task.result()

            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recv_task

    try:
        # --- First message: expect resume or treat as new session ---
        first_data: str = await websocket.receive_text()
        try:
            first_msg: dict[str, t.Any] = json.loads(first_data)
        except json.JSONDecodeError:
            first_msg = {}

        requested_id: str | None = None
        if first_msg.get("type") == "resume":
            requested_id = first_msg.get("session_id")

        session = _get_or_create_session(requested_id)
        is_resumed = requested_id is not None and requested_id == session.session_id

        # Tell the client which session they're on
        await websocket.send_text(json.dumps({
            "type": "session_start",
            "session_id": session.session_id,
            "resumed": is_resumed,
        }))

        # Replay history on resume
        if is_resumed and session.history:
            await websocket.send_text(json.dumps({
                "type": "history",
                "events": session.history,
            }))

        # If the first message was a regular user message (not resume), process it
        if first_msg.get("type") != "resume" and first_msg.get("content", "").strip():
            agent_task = asyncio.create_task(_run_agent(first_msg["content"]))

        # --- Main message loop ---
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

            if msg_type == "cancel":
                await _cancel_agent()
                continue

            user_input: str = msg.get("content", "")
            if not user_input.strip():
                continue

            await _cancel_agent()
            agent_task = asyncio.create_task(_run_agent(user_input))

    except WebSocketDisconnect:
        await _cancel_agent()
        # Session stays in _sessions for reconnect — NOT deleted here


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
