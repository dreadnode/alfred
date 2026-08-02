"""FastAPI backend — WebSocket chat + PDF file watcher."""

import asyncio
import contextlib
import json
import os
import re
import shutil
import tempfile
import time
import typing as t
import uuid

import yaml
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
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
from .capabilities import CAPABILITIES, maybe_expand_command

if t.TYPE_CHECKING:
    from dreadnode.agent import TaskAgent

# ---------------------------------------------------------------------------
# Module-level configuration (set once via ``configure()`` before server start)
# ---------------------------------------------------------------------------

from . import __version__ as VERSION

_paper_dir: str = ""
_model: str = ""
_workspace_root: str | None = None
_pdf_watcher_task: asyncio.Task[None] | None = None
_custom_pdf: str | None = None  # Override for the PDF viewer (external PDF)

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
    expired = [
        sid for sid, s in _sessions.items() if now - s.last_active > _SESSION_TTL
    ]
    for sid in expired:
        del _sessions[sid]


def _swap_model(new_model: str) -> None:
    """Replace agents in all sessions with a new model, preserving history.

    For each session:
    1. Copies the old agent's thread messages (conversation context)
    2. Creates a fresh agent with the new model
    3. Injects the old messages into the new agent's thread
    4. Appends a status event to the session's UI history
    """
    from copy import deepcopy

    for session in _sessions.values():
        # Preserve the old conversation thread
        old_messages = deepcopy(session.agent.thread.messages)

        # Create new agent with the new model
        session.agent = create_agent(new_model, _paper_dir)

        # Inject old conversation into the new agent's thread
        session.agent.thread.messages = old_messages

        # Record the swap in UI history
        session.history.append(
            {"type": "status", "content": f"Model changed to {new_model}."}
        )
        session.last_active = time.time()


def configure(
    paper_dir: str,
    model: str,
    workspace_root: str | None = None,
) -> None:
    """Store runtime configuration for the server.

    Must be called before ``uvicorn.run(app, ...)``.

    Args:
        paper_dir: Absolute path to the paper working directory.
        model: LLM model identifier forwarded to the agent.
        workspace_root: If set, enables workspace mode with multi-paper support.
    """
    global _paper_dir, _model, _workspace_root
    _paper_dir = os.path.abspath(paper_dir)
    _model = model
    _workspace_root = os.path.abspath(workspace_root) if workspace_root else None


# ---------------------------------------------------------------------------
# PDF file watcher
# ---------------------------------------------------------------------------

_PDF_DEBOUNCE: float = 1.5  # seconds to wait after last write before notifying


async def _watch_pdf() -> None:
    """Watch ``build/main.pdf`` for changes and notify connected WebSocket clients.

    Debounces notifications: waits ``_PDF_DEBOUNCE`` seconds after the last
    detected change before notifying, so the frontend doesn't load a
    partially-written PDF during multi-pass ``latexmk`` builds.
    """
    watch_dir = os.path.join(_paper_dir, "build")
    pdf_path = os.path.join(watch_dir, "main.pdf")

    if not os.path.isdir(watch_dir):
        os.makedirs(watch_dir, exist_ok=True)

    pending: asyncio.Task[None] | None = None

    async def _notify() -> None:
        """Wait for the debounce period, then notify all PDF clients."""
        await asyncio.sleep(_PDF_DEBOUNCE)
        # Verify the file exists and has content (not a truncated mid-write)
        if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) == 0:
            return
        msg = json.dumps({"type": "pdf_updated", "timestamp": time.time()})
        disconnected: set[WebSocket] = set()
        for ws in list(_pdf_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                disconnected.add(ws)
        _pdf_clients.difference_update(disconnected)

    async for changes in awatch(watch_dir):
        pdf_changed = any(path.endswith("main.pdf") for _, path in changes)
        if not pdf_changed:
            continue
        # Reset the debounce timer on each change
        if pending and not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending
        pending = asyncio.create_task(_notify())


async def _restart_pdf_watcher() -> None:
    """Cancel the current PDF watcher (if any) and start a new one."""
    global _pdf_watcher_task
    if _pdf_watcher_task:
        _pdf_watcher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _pdf_watcher_task
    _pdf_watcher_task = asyncio.create_task(_watch_pdf())


async def _switch_paper(new_paper_dir: str) -> None:
    """Switch the active paper directory at runtime."""
    global _paper_dir, _custom_pdf
    _paper_dir = os.path.abspath(new_paper_dir)
    _sessions.clear()

    # If the paper dir has a PDF file (e.g. from upload), show it automatically.
    # Otherwise reset to built PDF.
    _custom_pdf = None
    built_pdf = os.path.join(_paper_dir, "build", "main.pdf")
    if not os.path.isfile(built_pdf):
        # Look for a .pdf file in the paper directory root
        for fname in sorted(os.listdir(_paper_dir)):
            if fname.lower().endswith(".pdf"):
                _custom_pdf = os.path.join(_paper_dir, fname)
                break

    await _restart_pdf_watcher()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> t.AsyncIterator[None]:
    """Start the PDF watcher on server boot, cancel on shutdown."""
    global _pdf_watcher_task
    _pdf_watcher_task = asyncio.create_task(_watch_pdf())
    yield
    if _pdf_watcher_task:
        _pdf_watcher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _pdf_watcher_task


app = FastAPI(lifespan=_lifespan)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def get_config() -> dict[str, t.Any]:
    """Return the current server configuration (paper dir, model, title)."""
    title = ""
    yaml_path = os.path.join(_paper_dir, "paper.yaml")
    if os.path.isfile(yaml_path):
        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                title = data.get("title", "")
        except Exception:
            pass
    return {
        "paper_dir": _paper_dir,
        "model": _model,
        "paper_title": title,
        "workspace": _workspace_root is not None,
        "version": VERSION,
    }


@app.get("/api/commands")
async def list_commands() -> list[dict[str, str]]:
    """Return the list of available slash commands for autocomplete."""
    return [
        {
            "name": f"/{name}",
            "description": cap["description"],
            "arg_label": cap["arg_label"],
            "args": cap["args"],
        }
        for name, cap in sorted(CAPABILITIES.items())
    ]


@app.put("/api/paper-title")
async def update_paper_title(body: dict[str, t.Any]) -> dict[str, str]:
    """Update the paper title in ``paper.yaml``."""
    new_title: str = body.get("title", "").strip()
    if not new_title:
        return {"error": "title is required"}
    # Sanitize: strip control characters and limit length
    new_title = re.sub(r"[\x00-\x1f]+", " ", new_title).strip()
    if not new_title:
        return {"error": "title is required"}

    yaml_path = os.path.join(_paper_dir, "paper.yaml")
    if not os.path.isfile(yaml_path):
        return {"error": "paper.yaml not found"}

    try:
        with open(yaml_path) as f:
            content = f.read()
        # Use yaml.dump to produce a safely quoted scalar value
        safe_value = (
            yaml.dump(new_title, default_flow_style=True).replace("\n...\n", "").strip()
        )
        replacement = f"title: {safe_value}"
        new_content = re.sub(
            r"^title:\s*.*$",
            lambda _: replacement,
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if new_content == content:
            return {"error": "Could not find title field in paper.yaml"}
        with open(yaml_path, "w") as f:
            f.write(new_content)
    except Exception as exc:
        return {"error": f"Failed to update: {exc}"}

    return {"title": new_title}


def _slugify(title: str) -> str:
    """Convert a paper title to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    return slug or "untitled"


def _unique_slug(title: str, workspace: str) -> str:
    """Return a slug that doesn't collide with existing subdirs."""
    base = _slugify(title)
    slug = base
    n = 2
    while os.path.exists(os.path.join(workspace, slug)):
        slug = f"{base}-{n}"
        n += 1
    return slug


def _papers_dir() -> str:
    """Return the ``papers/`` subdirectory inside the workspace root."""
    assert _workspace_root is not None
    return os.path.join(_workspace_root, "papers")


def _list_papers() -> list[dict[str, t.Any]]:
    """Scan the workspace for paper subdirectories."""
    if not _workspace_root:
        return []
    pdir = _papers_dir()
    if not os.path.isdir(pdir):
        return []
    papers: list[dict[str, t.Any]] = []
    for name in sorted(os.listdir(pdir)):
        subdir = os.path.join(pdir, name)
        manifest = os.path.join(subdir, "paper.yaml")
        if not os.path.isdir(subdir) or not os.path.isfile(manifest):
            continue
        title = name
        try:
            with open(manifest) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                title = data.get("title", name)
        except Exception:
            pass
        papers.append(
            {
                "slug": name,
                "title": title,
                "active": os.path.abspath(subdir) == _paper_dir,
            }
        )
    return papers


@app.get("/api/papers")
async def list_papers() -> dict[str, t.Any]:
    """List all papers in the workspace."""
    return {
        "workspace": _workspace_root is not None,
        "papers": _list_papers(),
    }


@app.post("/api/papers")
async def create_paper(body: dict[str, t.Any]) -> dict[str, t.Any]:
    """Create a new paper in the workspace and switch to it."""
    if not _workspace_root:
        return {"error": "Not in workspace mode"}

    title: str = body.get("title", "").strip()
    if not title:
        return {"error": "title is required"}

    pdir = _papers_dir()
    os.makedirs(pdir, exist_ok=True)
    slug = _unique_slug(title, pdir)
    new_dir = os.path.join(pdir, slug)

    # Scaffold the new paper.
    import sys
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    scripts_dir = os.path.join(repo_root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from scaffold import scaffold_paper

    scaffold_paper(new_dir, title=title)

    await _switch_paper(new_dir)
    return {"slug": slug, "title": title, "paper_dir": new_dir}


@app.put("/api/papers/switch")
async def switch_paper(body: dict[str, t.Any]) -> dict[str, t.Any]:
    """Switch the active paper in the workspace."""
    if not _workspace_root:
        return {"error": "Not in workspace mode"}

    slug: str = body.get("slug", "").strip()
    if not slug:
        return {"error": "slug is required"}

    target = os.path.join(_papers_dir(), slug)
    if not os.path.isfile(os.path.join(target, "paper.yaml")):
        return {"error": f"Paper '{slug}' not found"}

    await _switch_paper(target)

    # Read title from the paper we switched to.
    title = slug
    try:
        with open(os.path.join(target, "paper.yaml")) as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            title = data.get("title", slug)
    except Exception:
        pass

    return {"slug": slug, "title": title, "paper_dir": target}


@app.post("/api/config")
async def update_config(body: dict[str, t.Any]) -> dict[str, str]:
    """Update model and API key at runtime.

    Accepts one of two key forms (exactly one required):

    * ``api_key``: a raw key value — stored into the env var named by
      ``api_key_env`` (which is required alongside it).
    * ``api_key_env``: the name of an environment variable that already
      holds the key (e.g. ``ANTHROPIC_API_KEY``).

    Clears all active sessions so the next WebSocket connection creates a
    fresh agent with the new model.
    """
    global _model

    new_model: str = body.get("model", "").strip()
    api_key: str = body.get("api_key", "").strip()
    api_key_env: str = body.get("api_key_env", "").strip()

    if not new_model:
        return {"error": "model is required"}

    if api_key and api_key_env:
        # Raw key provided — store it in the named env var.
        os.environ[api_key_env] = api_key
        if api_key_env == "OPENROUTER_API_KEY" and not new_model.startswith(
            "openrouter/"
        ):
            new_model = f"openrouter/{new_model}"
    elif api_key_env:
        # Env var name only — verify it's set.
        if not os.environ.get(api_key_env):
            return {"error": f"Environment variable '{api_key_env}' is not set"}
        if api_key_env == "OPENROUTER_API_KEY" and not new_model.startswith(
            "openrouter/"
        ):
            new_model = f"openrouter/{new_model}"
    else:
        return {"error": "Provide either an API key or an environment variable name"}

    _model = new_model

    # Recreate agents with new model, preserving chat history and thread.
    _swap_model(new_model)

    return {"model": _model}


@app.delete("/api/chat-history")
async def clear_chat_history() -> dict[str, str]:
    """Delete the on-disk chat history backup."""
    backup_path = os.path.join(_paper_dir, ".chat-history.json")
    with contextlib.suppress(OSError):
        os.unlink(backup_path)
    return {"status": "cleared"}


@app.get("/api/pdf", response_model=None)
async def get_pdf() -> FileResponse | JSONResponse:
    """Serve the loaded PDF (custom or built)."""
    pdf_path = _custom_pdf or os.path.join(_paper_dir, "build", "main.pdf")
    if not os.path.exists(pdf_path):
        return JSONResponse({"error": "PDF not found"}, status_code=404)
    return FileResponse(pdf_path, media_type="application/pdf")


async def _create_paper_for_pdf(
    pdf_path: str, filename: str | None = None
) -> dict[str, str] | None:
    """In workspace mode, create a paper directory for an external PDF.

    Args:
        pdf_path: Path to the PDF file on disk.
        filename: Original filename (for title derivation). Falls back to basename of pdf_path.

    Returns ``{"slug": ..., "title": ..., "pdf_path": ...}`` if created, else ``None``.
    """
    if not _workspace_root:
        return None
    # Skip if the PDF is already inside the active paper directory
    paper_prefix = os.path.abspath(_paper_dir) + os.sep
    if os.path.abspath(pdf_path).startswith(paper_prefix):
        return None

    display_name = os.path.basename(filename or pdf_path)
    title = _title_from_filename(display_name)
    pdir = _papers_dir()
    os.makedirs(pdir, exist_ok=True)
    slug = _unique_slug(title, pdir)
    new_dir = os.path.join(pdir, slug)

    import sys
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parent.parent.parent)
    scripts_dir = os.path.join(repo_root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from scaffold import scaffold_paper

    scaffold_paper(new_dir, title=title)

    # Copy the PDF into the new paper directory
    dest = os.path.join(new_dir, display_name)
    shutil.copy2(pdf_path, dest)

    await _switch_paper(new_dir)
    return {"slug": slug, "title": title, "pdf_path": dest}


@app.post("/api/load-pdf")
async def load_pdf(body: dict[str, t.Any]) -> dict[str, t.Any]:
    """Load an external PDF into the viewer."""
    global _custom_pdf
    path: str = body.get("path", "").strip()
    if not path:
        return {"error": "path is required"}
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(_paper_dir, expanded)
    if not os.path.isfile(expanded):
        return {"error": f"File not found: {path}"}
    if not expanded.lower().endswith(".pdf"):
        return {"error": "File must be a PDF"}
    expanded = os.path.abspath(expanded)

    # In workspace mode, create a paper directory for external PDFs
    paper_info = await _create_paper_for_pdf(expanded)
    if paper_info:
        _custom_pdf = os.path.abspath(paper_info["pdf_path"])
    else:
        _custom_pdf = expanded

    # Notify PDF clients so the viewer reloads
    msg = json.dumps({"type": "pdf_updated", "timestamp": time.time()})
    for ws in list(_pdf_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            _pdf_clients.discard(ws)
    result: dict[str, t.Any] = {"path": _custom_pdf}
    if paper_info:
        result["paper_created"] = {
            "slug": paper_info["slug"],
            "title": paper_info["title"],
        }
    return result


@app.post("/api/reset-pdf")
async def reset_pdf() -> dict[str, str]:
    """Reset the PDF viewer back to the built paper."""
    global _custom_pdf
    _custom_pdf = None
    msg = json.dumps({"type": "pdf_updated", "timestamp": time.time()})
    for ws in list(_pdf_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            _pdf_clients.discard(ws)
    return {"status": "reset"}


def _title_from_filename(filename: str) -> str:
    """Derive a human-readable title from a PDF filename."""
    # Strip .pdf extension (handles ".pdf" edge case where splitext treats it as stem)
    name = filename
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    # Replace common separators with spaces
    name = re.sub(r"[-_.]+", " ", name)
    return name.strip().title() or "Untitled"


@app.post("/api/upload-pdf")
async def upload_pdf(file: UploadFile) -> dict[str, t.Any]:
    """Upload a PDF, load it into the viewer, and extract text for the agent."""
    global _custom_pdf
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return {"error": "File must be a PDF"}

    # Clean up previous upload (only delete temp files we created)
    if _custom_pdf and os.path.basename(_custom_pdf).startswith("al-upload-"):
        with contextlib.suppress(OSError):
            os.unlink(_custom_pdf)

    # Save to a temp location
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="al-upload-")
    content = await file.read()
    tmp.write(content)
    tmp.close()

    _custom_pdf = tmp.name

    # In workspace mode, create a paper directory for this PDF
    paper_info = await _create_paper_for_pdf(tmp.name, filename=file.filename)
    paper_created = None
    if paper_info:
        _custom_pdf = os.path.abspath(paper_info["pdf_path"])
        # Clean up the temp file — PDF has been copied into the paper directory
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)
        paper_created = {"slug": paper_info["slug"], "title": paper_info["title"]}

    # Notify PDF clients
    msg = json.dumps({"type": "pdf_updated", "timestamp": time.time()})
    for ws in list(_pdf_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            _pdf_clients.discard(ws)

    # Extract text via pdftotext if available
    extracted = ""
    text_ok = False
    try:
        proc = await asyncio.create_subprocess_exec(
            "pdftotext",
            _custom_pdf or tmp.name,
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        extracted = stdout.decode("utf-8", errors="replace")
        text_ok = bool(extracted.strip())
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        extracted = "Text extraction timed out"
    except FileNotFoundError:
        extracted = "pdftotext not installed — text extraction unavailable"
    except Exception as exc:
        extracted = f"Text extraction failed: {exc}"

    result: dict[str, t.Any] = {
        "filename": file.filename,
        "path": _custom_pdf or tmp.name,
        "text": extracted,
        "text_ok": text_ok,
    }
    if paper_created:
        result["paper_created"] = paper_created
    return result


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
        If a backup file exists and no in-memory session matches, restores
        the session history from disk.
        """
        _prune_sessions()
        if session_id and session_id in _sessions:
            _sessions[session_id].last_active = time.time()
            return _sessions[session_id]

        new_id = str(uuid.uuid4())
        new_session = _Session(
            session_id=new_id,
            agent=create_agent(_model, _paper_dir),
        )

        # Restore history from disk backup if available
        backup_path = os.path.join(_paper_dir, ".chat-history.json")
        if os.path.isfile(backup_path):
            try:
                with open(backup_path) as f:
                    backup = json.load(f)
                if isinstance(backup.get("history"), list):
                    new_session.history = backup["history"]
            except Exception:
                pass  # Corrupted backup — start fresh

        _sessions[new_id] = new_session
        return new_session

    async def _send_event(event_dict: dict[str, t.Any]) -> None:
        """Send a formatted event to the client and record it in session history."""
        if session:
            session.history.append(event_dict)
        await websocket.send_text(json.dumps(event_dict))

    def _persist_history() -> None:
        """Write session history to disk as a backup (atomic via rename)."""
        if not session:
            return
        backup_path = os.path.join(_paper_dir, ".chat-history.json")
        tmp_path = backup_path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(
                    {
                        "session_id": session.session_id,
                        "history": session.history,
                        "timestamp": time.time(),
                    },
                    f,
                )
            os.replace(tmp_path, backup_path)
        except Exception:
            pass  # Best-effort — don't crash the agent loop

    async def _run_agent(user_input: str) -> None:
        """Stream agent events to the WebSocket. Runs inside a cancellable task."""
        assert session is not None
        session.last_active = time.time()
        user_event: dict[str, t.Any] = {"type": "user_message", "content": user_input}
        session.history.append(user_event)
        expanded = maybe_expand_command(user_input)
        try:
            async with session.agent.stream(expanded) as events:
                async for event in events:
                    # Detect corrupted history from tool_use/tool_result mismatch
                    if isinstance(event, AgentError):
                        err_str = str(event.error)
                        if "tool_use" in err_str and "tool_result" in err_str:
                            session.agent = create_agent(_model, _paper_dir)
                            session.history.clear()
                            await _send_event(
                                {
                                    "type": "error",
                                    "message": "Session had corrupted history — reset automatically. Please resend your message.",
                                }
                            )
                            await _send_event(
                                {
                                    "type": "agent_end",
                                    "stop_reason": "error_recovery",
                                    "failed": True,
                                    "steps": 0,
                                    "usage": {
                                        "input_tokens": 0,
                                        "output_tokens": 0,
                                        "total_tokens": 0,
                                    },
                                }
                            )
                            _persist_history()
                            return
                    formatted = _format_event(event)
                    if formatted:
                        await _send_event(formatted)
            _persist_history()
        except asyncio.CancelledError:
            try:
                await _send_event(
                    {
                        "type": "agent_end",
                        "stop_reason": "cancelled",
                        "failed": True,
                        "steps": 0,
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
                )
            except WebSocketDisconnect:
                pass  # Client already gone — event is still recorded in history
            _persist_history()
        except WebSocketDisconnect:
            raise
        except Exception as exc:
            # Detect corrupted conversation history (dangling tool_use without
            # tool_result) and auto-recover with a fresh agent.
            err_str = str(exc)
            if "tool_use" in err_str and "tool_result" in err_str:
                session.agent = create_agent(_model, _paper_dir)
                session.history.clear()
                try:
                    await _send_event(
                        {
                            "type": "error",
                            "message": "Session had corrupted history — reset automatically. Please resend your message.",
                        }
                    )
                    await _send_event(
                        {
                            "type": "agent_end",
                            "stop_reason": "error_recovery",
                            "failed": True,
                            "steps": 0,
                            "usage": {
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 0,
                            },
                        }
                    )
                except WebSocketDisconnect:
                    raise
                _persist_history()
                return
            try:
                await _send_event(
                    {
                        "type": "error",
                        "message": f"Agent error: {exc}",
                    }
                )
                await _send_event(
                    {
                        "type": "agent_end",
                        "stop_reason": "error",
                        "failed": True,
                        "steps": 0,
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
                )
            except WebSocketDisconnect:
                raise
            _persist_history()

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
        await websocket.send_text(
            json.dumps(
                {
                    "type": "session_start",
                    "session_id": session.session_id,
                    "resumed": is_resumed,
                }
            )
        )

        # Replay history on resume
        if is_resumed and session.history:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "history",
                        "events": session.history,
                    }
                )
            )

        # If the first message was a regular user message (not resume), process it
        if first_msg.get("type") != "resume" and first_msg.get("content", "").strip():
            agent_task = asyncio.create_task(_run_agent(first_msg["content"]))

        # --- Main message loop ---
        while True:
            data: str = await _recv_message()

            try:
                msg: dict[str, t.Any] = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "Invalid JSON received",
                        }
                    )
                )
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
