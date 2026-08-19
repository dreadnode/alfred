"""Tests for ui/backend — tools, agent factory, event formatting, sessions."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import stat
import sys
import tempfile
import typing as t
from contextlib import asynccontextmanager, contextmanager, suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.types import Message

# Add ui/ to path so we can import backend.*
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
sys.path.insert(0, UI_DIR)

import backend.server as srv  # noqa: E402
from backend.agent import (  # noqa: E402
    _load_paper_context,
    create_agent,
    extract_image_content,
)
from backend.db import Database  # noqa: E402
from backend.server import _format_event, app  # noqa: E402
from backend.sessions import SessionService  # noqa: E402
from backend.tools.subprocess import run_script  # noqa: E402
from backend.tools.web import (  # noqa: E402
    _check_url,
    _is_internal,
    _strip_html,
    web_fetch,
)

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_server_globals() -> t.Iterator[None]:
    """Restore mutable server registries after every test.

    The backend intentionally keeps process-wide caches for live sessions. Tests
    must not leave entries behind: doing so makes later cases depend on execution
    order and can conceal missing cleanup in the code under test.
    """
    registry_names = (
        "_agents",
        "_locks",
        "_conns",
        "_session_tasks",
        "_session_task_groups",
        "_thread_restore_failures",
        "_custom_pdfs",
        "_uploaded_pdfs",
        "_pdf_clients",
        "_session_id_for_paper_dir",
    )
    snapshots = {name: getattr(srv, name).copy() for name in registry_names}
    old_pdf_watcher_task = srv._pdf_watcher_task

    try:
        yield
    finally:
        pending_tasks = {
            *srv._session_tasks.values(),
            *(task for tasks in srv._session_task_groups.values() for task in tasks),
        }
        for task in pending_tasks:
            if not task.done():
                task.cancel()

        for name, snapshot in snapshots.items():
            registry = getattr(srv, name)
            registry.clear()
            registry.update(snapshot)
        srv._pdf_watcher_task = old_pdf_watcher_task


@contextmanager
def _server_state(
    tmp_path: t.Any,
    model: str = "test-model",
) -> t.Iterator[tuple[Database, SessionService]]:
    """Set up app.state.db and app.state.svc with a temp SQLite database.

    Saves and restores server globals (_model, _papers_root) and app.state
    on exit so tests don't pollute each other.
    """
    papers_root = str(tmp_path / "papers")
    os.makedirs(papers_root, exist_ok=True)
    db_path = str(tmp_path / "state.db")

    old_model = srv._model
    old_papers_root = srv._papers_root
    missing = object()
    old_db = getattr(app.state, "db", missing)
    old_svc = getattr(app.state, "svc", missing)

    db = Database(db_path)
    asyncio.run(db.connect())
    svc = SessionService(db, papers_root)

    srv._model = model
    srv._papers_root = papers_root
    app.state.db = db
    app.state.svc = svc

    try:
        yield db, svc
    finally:
        asyncio.run(db.close())
        srv._model = old_model
        srv._papers_root = old_papers_root
        if old_db is missing:
            del app.state.db
        else:
            app.state.db = old_db
        if old_svc is missing:
            del app.state.svc
        else:
            app.state.svc = old_svc


# ---------------------------------------------------------------------------
# Browser trust boundary
# ---------------------------------------------------------------------------


class TestBrowserTrustBoundary:
    @staticmethod
    def _request_status(host: str) -> int:
        """Issue a minimal ASGI request through the app's middleware stack."""

        async def _request() -> int:
            messages: list[Message] = []

            async def receive() -> Message:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: Message) -> None:
                messages.append(message)

            await app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.3"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/api/config",
                    "raw_path": b"/api/config",
                    "query_string": b"",
                    "root_path": "",
                    "headers": [(b"host", host.encode())],
                    "client": ("127.0.0.1", 12345),
                    "server": ("127.0.0.1", 8420),
                },
                receive,
                send,
            )
            return next(
                message["status"]
                for message in messages
                if message["type"] == "http.response.start"
            )

        return asyncio.run(_request())

    def test_accepts_local_host_header(self) -> None:
        assert self._request_status("localhost:8420") == 200

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
    def test_managed_directories_are_owner_only(self, tmp_path: t.Any) -> None:
        managed = tmp_path / "managed"
        managed.mkdir(mode=0o755)
        os.chmod(managed, 0o755)

        srv._ensure_private_directory(str(managed))

        assert stat.S_IMODE(managed.stat().st_mode) == 0o700

    @pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
    def test_managed_directories_must_not_be_symlinks(self, tmp_path: t.Any) -> None:
        target = tmp_path / "target"
        target.mkdir()
        managed = tmp_path / "managed"
        managed.symlink_to(target, target_is_directory=True)

        with pytest.raises(NotADirectoryError, match="must not be a symlink"):
            srv._ensure_private_directory(str(managed))

    def test_rejects_nonlocal_host_header(self) -> None:
        assert self._request_status("attacker.example") == 400

    @pytest.mark.parametrize(
        "origin",
        [
            "http://localhost:8420",
            "http://127.0.0.1:8420",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    )
    def test_accepts_configured_local_websocket_origins(self, origin: str) -> None:
        allowed = {
            "http://localhost:8420",
            "http://127.0.0.1:8420",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        }

        with patch.object(srv, "_allowed_websocket_origins", allowed):
            assert srv._is_allowed_websocket_origin(origin)

    @pytest.mark.parametrize(
        "origin",
        [
            None,
            "null",
            "https://attacker.example",
            "http://localhost.attacker.example:8420",
            "http://localhost:8420/with-a-path",
            "ws://localhost:8420",
        ],
    )
    def test_rejects_untrusted_websocket_origins(self, origin: str | None) -> None:
        assert not srv._is_allowed_websocket_origin(origin)

    @pytest.mark.parametrize("handler", [srv.ws_pdf, srv.ws_chat])
    def test_websocket_handlers_reject_before_accepting(
        self,
        handler: t.Callable[[t.Any], t.Coroutine[t.Any, t.Any, None]],
    ) -> None:
        websocket = MagicMock()
        websocket.headers = {"origin": "https://attacker.example"}
        websocket.close = AsyncMock()
        websocket.accept = AsyncMock()

        asyncio.run(handler(websocket))

        websocket.close.assert_awaited_once_with(
            code=1008,
            reason="WebSocket origin not allowed",
        )
        websocket.accept.assert_not_awaited()


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_removes_tags(self) -> None:
        assert _strip_html("<div><p>hello <b>world</b></p></div>") == "hello world"

    def test_removes_script_blocks(self) -> None:
        html = '<p>before</p><script type="text/javascript">alert("xss")</script><p>after</p>'
        result = _strip_html(html)
        assert "alert" not in result
        assert "before" in result
        assert "after" in result

    def test_removes_style_blocks(self) -> None:
        result = _strip_html("<style>.foo { color: red; }</style><p>content</p>")
        assert "color" not in result
        assert "content" in result

    def test_removes_comments(self) -> None:
        result = _strip_html("<p>before</p><!-- secret --><p>after</p>")
        assert "secret" not in result

    def test_decodes_named_entities(self) -> None:
        assert _strip_html("<p>AT&amp;T &lt;3&gt;</p>") == "AT&T <3>"

    def test_decodes_numeric_entities(self) -> None:
        assert _strip_html("<p>&#8217;</p>") == "’"

    def test_collapses_whitespace(self) -> None:
        assert _strip_html("<p>  lots   of    space  </p>") == "lots of space"

    def test_empty_input(self) -> None:
        assert _strip_html("") == ""


# ---------------------------------------------------------------------------
# _load_paper_context
# ---------------------------------------------------------------------------


class TestLoadPaperContext:
    def test_full_paper(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text(
            'title: "My Paper"\n'
            "template: neurips2024\n"
            "authors:\n"
            '  - name: "Alice"\n'
            '  - name: "Bob"\n'
            "abstract_summary: A paper about things.\n"
            "sections:\n"
            '  - slug: "00_abstract"\n'
            '    title: "Abstract"\n'
            "    status: complete\n"
            '  - slug: "01_intro"\n'
            '    title: "Introduction"\n'
            "    status: draft\n"
            "macros:\n"
            '  NumModels: "5"\n'
            "styles:\n"
            "  - messageboxes\n"
        )
        ctx = _load_paper_context(str(tmp_path))
        assert "My Paper" in ctx
        assert "neurips2024" in ctx
        assert "Alice" in ctx
        assert "Bob" in ctx
        assert "A paper about things." in ctx
        assert "[complete] 00_abstract" in ctx
        assert "[draft] 01_intro" in ctx
        assert "NumModels" in ctx
        assert "messageboxes" in ctx

    def test_missing_yaml(self, tmp_path: t.Any) -> None:
        assert _load_paper_context(str(tmp_path)) == ""

    def test_invalid_yaml(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text("[unterminated")
        assert _load_paper_context(str(tmp_path)) == ""

    def test_minimal_yaml(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text("title: Untitled\n")
        ctx = _load_paper_context(str(tmp_path))
        assert "Untitled" in ctx

    def test_non_dict_macros(self, tmp_path: t.Any) -> None:
        """macros as a list should not crash."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\nmacros:\n  - foo\n')
        ctx = _load_paper_context(str(tmp_path))
        assert "Macros defined" not in ctx

    def test_non_list_styles(self, tmp_path: t.Any) -> None:
        """styles as a string should not crash."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\nstyles: "messageboxes"\n')
        ctx = _load_paper_context(str(tmp_path))
        assert "Style packages" not in ctx


# ---------------------------------------------------------------------------
# run_script
# ---------------------------------------------------------------------------


class TestRunScript:
    def test_success(self) -> None:
        result = asyncio.run(run_script("echo", "hello", cwd="/tmp"))
        assert result.strip() == "hello"

    def test_nonzero_exit_raises_runtime_error(self) -> None:
        with pytest.raises(RuntimeError, match="failed"):
            asyncio.run(run_script("false", cwd="/tmp"))

    def test_timeout_raises(self) -> None:
        started = asyncio.Event()
        proc = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        async def communicate() -> t.NoReturn:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        proc.communicate = communicate

        async def _run() -> None:
            with patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ):
                with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                    await run_script("sleep", "10", cwd="/tmp", timeout=0.01)

        asyncio.run(_run())
        assert started.is_set()
        proc.kill.assert_called_once_with()
        proc.wait.assert_awaited_once_with()

    def test_stderr_merged_into_stdout(self) -> None:
        result = asyncio.run(
            run_script("bash", "-c", "echo out && echo err >&2", cwd="/tmp")
        )
        assert "out" in result
        assert "err" in result

    def test_cancellation_kills_child_process(self) -> None:
        """Cancelling the task kills and reaps the subprocess."""
        started = asyncio.Event()
        proc = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        async def communicate() -> t.NoReturn:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        proc.communicate = communicate

        async def _run() -> None:
            with patch(
                "asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=proc),
            ):
                task = asyncio.create_task(
                    run_script("sleep", "60", cwd="/tmp", timeout=120)
                )
                await started.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        asyncio.run(_run())
        proc.kill.assert_called_once_with()
        proc.wait.assert_awaited_once_with()


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


class TestIsInternal:
    @pytest.mark.parametrize(
        "addr",
        [
            "10.0.0.1",          # is_private (RFC 1918)
            "169.254.169.254",   # is_link_local (AWS metadata)
            "::1",               # IPv6 loopback
        ],
    )
    def test_blocks_internal(self, addr: str) -> None:
        import ipaddress

        assert _is_internal(ipaddress.ip_address(addr))

    def test_blocks_ipv4_mapped_ipv6(self) -> None:
        import ipaddress

        assert _is_internal(ipaddress.ip_address("::ffff:127.0.0.1"))

    def test_allows_public(self) -> None:
        import ipaddress

        assert not _is_internal(ipaddress.ip_address("8.8.8.8"))


class TestCheckUrl:
    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(ValueError, match="Blocked URL scheme"):
            asyncio.run(_check_url("file:///etc/passwd"))

    def test_rejects_no_hostname(self) -> None:
        with pytest.raises(ValueError, match="No hostname"):
            asyncio.run(_check_url("http:///path"))

    def test_blocks_internal_via_dns(self) -> None:
        with pytest.raises(ValueError, match="internal address"):
            asyncio.run(_check_url("http://localhost/secret"))

    def test_allows_public_url(self) -> None:
        asyncio.run(_check_url("https://arxiv.org/abs/2301.00001"))


# ---------------------------------------------------------------------------
# web_fetch
# ---------------------------------------------------------------------------


def _mock_aiohttp(content_type: str, body: bytes) -> t.Any:
    """Create a mocked aiohttp ClientSession for web_fetch tests."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content_type = content_type
    mock_resp.content.read = AsyncMock(return_value=body)
    mock_resp.get_encoding = MagicMock(return_value="utf-8")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    # session.get() must return an async context manager, not a coroutine
    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return mock_session


class TestWebFetch:
    def test_fetches_html_and_strips(self) -> None:
        """HTML content is stripped to plain text."""
        session = _mock_aiohttp("text/html", b"<p>hello &amp; world</p>")
        with patch("backend.tools.web.aiohttp.ClientSession", return_value=session):
            result = asyncio.run(web_fetch.fn(url="https://example.com"))
        assert result == "hello & world"

    def test_rejects_binary_content_type(self) -> None:
        """PDF and other binary types should raise ValueError."""
        session = _mock_aiohttp("application/pdf", b"")
        with patch("backend.tools.web.aiohttp.ClientSession", return_value=session):
            with pytest.raises(ValueError, match="Non-text"):
                asyncio.run(web_fetch.fn(url="https://example.com/file.pdf"))

    def test_plain_text_not_stripped(self) -> None:
        """text/plain should be returned without HTML stripping."""
        session = _mock_aiohttp("text/plain", b"<not-html> just text")
        with patch("backend.tools.web.aiohttp.ClientSession", return_value=session):
            result = asyncio.run(web_fetch.fn(url="https://example.com/file.txt"))
        assert "<not-html>" in result

    def test_truncation(self) -> None:
        """Output exceeding max_chars should be truncated."""
        session = _mock_aiohttp("text/plain", b"x" * 1000)
        with patch("backend.tools.web.aiohttp.ClientSession", return_value=session):
            result = asyncio.run(web_fetch.fn(url="https://example.com", max_chars=100))
        assert len(result) < 200
        assert "[truncated]" in result


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_dir(tmp_path: t.Any) -> str:
    """Temp directory with minimal paper.yaml for agent creation."""
    (tmp_path / "paper.yaml").write_text('title: "Test Paper"\n')
    return str(tmp_path)


class TestCreateAgent:
    def test_basic_properties(self, agent_dir: str) -> None:
        agent = create_agent("test-model", agent_dir)
        assert agent.name == "latex-agent"
        assert agent.max_steps == 50

    def test_expected_tools_present(self, agent_dir: str) -> None:
        agent = create_agent("test-model", agent_dir)
        names = {t.name for t in agent.all_tools}
        expected = {
            "build_paper",
            "sync_paper",
            "validate_paper",
            "search_citations",
            "add_citation",
            "paper_stats",
            "generate_diff",
            "switch_template",
            "list_templates",
            "list_reviews",
            "show_pdf",
            "show_project_pdf",
            "read_pdf",
            "build_paper_and_show",
            "web_fetch",
            "web_search",
            "command",
            "read_file",
            "write_file",
            "save_capability_report",
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

    def test_task_lifecycle_controls_removed(self, agent_dir: str) -> None:
        """Local chat agents must not inherit one-shot task controls."""
        agent = create_agent("test-model", agent_dir)
        tool_names = {tool.name for tool in agent.all_tools}
        stop_condition_names = {condition.name for condition in agent.stop_conditions}

        assert tool_names.isdisjoint({"finish_task", "give_up_on_task", "update_todo"})
        assert "stop_never" not in stop_condition_names

    def test_capability_report_tool_confines_output(self, tmp_path: t.Any) -> None:
        """Capability reports land in the repo report directory only."""
        import backend.tools.latex as latex_tools

        with patch.object(latex_tools, "_REPO_ROOT", str(tmp_path)):
            tool = next(
                item
                for item in latex_tools.make_latex_tools(str(tmp_path), "s-test")
                if item.name == "save_capability_report"
            )
            result = asyncio.run(tool.fn("report.md", "# Report\n"))
            report = tmp_path / "capabilities" / "reports" / "report.md"
            assert report.read_text() == "# Report\n"
            assert str(report) in result

            with pytest.raises(ValueError, match="simple .md basename"):
                asyncio.run(tool.fn("../../outside.md", "bad"))
            assert not (tmp_path.parent / "outside.md").exists()

    def test_latex_tools_no_paper_dir_param(self, agent_dir: str) -> None:
        """Latex tools should not expose paper_dir to the LLM."""
        agent = create_agent("test-model", agent_dir)
        for tool in agent.all_tools:
            if tool.name in ("build_paper", "sync_paper", "paper_stats"):
                params = (tool.api_definition.function.parameters or {}).get(
                    "properties", {}
                )
                assert "paper_dir" not in params, f"{tool.name} exposes paper_dir"

    def test_paper_context_in_instructions(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text(
            'title: "My Great Paper"\n'
            "sections:\n"
            '  - slug: "01_intro"\n'
            '    title: "Introduction"\n'
            "    status: in_progress\n"
        )
        agent = create_agent("test-model", str(tmp_path))
        instructions = agent.instructions or ""
        assert "My Great Paper" in instructions
        assert "[in_progress] 01_intro" in instructions

    def test_hooks_registered(self, agent_dir: str) -> None:
        agent = create_agent("test-model", agent_dir)
        hook_names = [getattr(h, "__name__", type(h).__name__) for h in agent.hooks]
        assert "summarize_when_long" in hook_names
        assert "retry_with_feedback" in hook_names

    def test_web_search_present_and_no_key_required(self, agent_dir: str) -> None:
        """web_search should be available without any API key configuration."""
        agent = create_agent("test-model", agent_dir)
        search_tool = next(t for t in agent.all_tools if t.name == "web_search")
        params = (search_tool.api_definition.function.parameters or {}).get(
            "properties", {}
        )
        assert "query" in params
        assert "api_key" not in params


# ---------------------------------------------------------------------------
# _format_event
# ---------------------------------------------------------------------------


def _base_fields() -> dict[str, t.Any]:
    """Common fields required by AgentEvent dataclasses."""
    agent = MagicMock()
    agent.name = "test-agent"
    agent._generator = None
    return {
        "session_id": MagicMock(),
        "agent": agent,
        "thread": MagicMock(),
        "messages": [],
        "events": [],
    }


def _make_event(cls_path: str, **kwargs: t.Any) -> t.Any:
    """Import an event class by dotted name and instantiate with base fields."""
    module_path, cls_name = cls_path.rsplit(".", 1)
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    return cls(**_base_fields(), **kwargs)


class TestFormatEvent:
    """Test _format_event across all event types."""

    @pytest.mark.parametrize(
        "cls_path, extra_kwargs, expected",
        [
            (
                "dreadnode.agent.events.AgentStart",
                {},
                {"type": "agent_start", "agent": "test-agent"},
            ),
            (
                "dreadnode.agent.events.StepStart",
                {"step": 3},
                {"type": "step_start", "step": 3},
            ),
            ("dreadnode.agent.events.AgentStalled", {}, {"type": "stalled"}),
            ("dreadnode.agent.events.AgentEvent", {}, None),
        ],
        ids=["agent_start", "step_start", "stalled", "unknown_returns_none"],
    )
    def test_simple_events(
        self, cls_path: str, extra_kwargs: dict, expected: t.Any
    ) -> None:
        event = _make_event(cls_path, **extra_kwargs)
        assert _format_event(event) == expected

    def test_generation_end(self) -> None:
        import rigging as rg

        msg = rg.Message("assistant", "Here is my response.")
        usage = rg.generator.Usage(input_tokens=100, output_tokens=50, total_tokens=150)
        result = _format_event(
            _make_event(
                "dreadnode.agent.events.GenerationEnd", message=msg, usage=usage
            )
        )
        assert result is not None
        assert result["type"] == "generation"
        assert result["content"] == "Here is my response."
        assert result["role"] == "assistant"
        assert result["usage"]["total_tokens"] == 150

    def test_generation_end_no_usage(self) -> None:
        import rigging as rg

        msg = rg.Message("assistant", "Response without usage.")
        result = _format_event(
            _make_event("dreadnode.agent.events.GenerationEnd", message=msg, usage=None)
        )
        assert result is not None
        assert result["usage"] is None
        assert result["content"] == "Response without usage."

    def test_tool_start(self) -> None:
        tc = MagicMock()
        tc.name = "build_paper"
        tc.function.arguments = '{"timeout": 120}'
        result = _format_event(
            _make_event("dreadnode.agent.events.ToolStart", tool_call=tc)
        )
        assert result == {
            "type": "tool_start",
            "tool": "build_paper",
            "args": '{"timeout": 120}',
        }

    def test_tool_end_truncates(self) -> None:
        import rigging as rg

        tc = MagicMock()
        tc.name = "web_fetch"
        msg = rg.Message("tool", "x" * 3000)
        result = _format_event(
            _make_event(
                "dreadnode.agent.events.ToolEnd", tool_call=tc, message=msg, stop=False
            )
        )
        assert result is not None
        assert len(result["result"]) == 2000
        assert result["stop"] is False

    def test_agent_error(self) -> None:
        result = _format_event(
            _make_event("dreadnode.agent.events.AgentError", error=RuntimeError("boom"))
        )
        assert result is not None
        assert result["type"] == "error"
        assert "boom" in result["message"]

    @pytest.mark.parametrize(
        "reaction_cls, kwargs, expected_substr",
        [
            ("RetryWithFeedback", {"feedback": "Try again."}, "RetryWithFeedback"),
            ("Finish", {"reason": "Task complete"}, "Finish"),
            ("Fail", {"error": "Out of retries"}, "Fail"),
        ],
        ids=["retry", "finish", "fail"],
    )
    def test_reacted(
        self, reaction_cls: str, kwargs: dict, expected_substr: str
    ) -> None:
        from dreadnode import agent as _a

        reaction = getattr(_a.reactions, reaction_cls)(**kwargs)
        result = _format_event(
            _make_event(
                "dreadnode.agent.events.Reacted", hook_name="h", reaction=reaction
            )
        )
        assert result is not None
        assert result["type"] == "reacted"
        assert expected_substr in result["content"]

    def test_agent_end(self) -> None:
        import rigging as rg
        from dreadnode.agent.result import AgentResult

        mock_result = MagicMock(spec=AgentResult)
        mock_result.failed = False
        mock_result.steps = 5
        mock_result.usage = rg.generator.Usage(
            input_tokens=500, output_tokens=200, total_tokens=700
        )
        result = _format_event(
            _make_event(
                "dreadnode.agent.events.AgentEnd",
                stop_reason="finished",
                result=mock_result,
            )
        )
        assert result is not None
        assert result["type"] == "agent_end"
        assert result["failed"] is False
        assert result["steps"] == 5
        assert result["usage"]["total_tokens"] == 700


# ---------------------------------------------------------------------------
# Session REST endpoints
# ---------------------------------------------------------------------------


class TestSessionEndpoints:
    """Test session CRUD via the FastAPI endpoint functions."""

    def test_create_and_list(self, tmp_path: t.Any) -> None:
        """POST /api/sessions creates; GET /api/sessions returns it."""
        with _server_state(tmp_path):
            created = asyncio.run(srv.api_create_session({"label": "My Paper"}))
            assert created["id"].startswith("s-")
            assert created["label"] == "My Paper"
            assert created["paper_dir"] is None

            result = asyncio.run(srv.api_list_sessions())
            assert len(result["sessions"]) == 1
            assert result["sessions"][0]["id"] == created["id"]

    def test_create_with_no_body(self, tmp_path: t.Any) -> None:
        """POST /api/sessions with no body uses defaults."""
        with _server_state(tmp_path):
            created = asyncio.run(srv.api_create_session(None))
            assert created["id"].startswith("s-")
            assert created["label"] == "New Session"

    def test_delete(self, tmp_path: t.Any) -> None:
        """DELETE /api/sessions/{id} removes the session."""
        with _server_state(tmp_path):
            created = asyncio.run(srv.api_create_session({"label": "Doomed"}))
            result = asyncio.run(srv.api_delete_session(created["id"]))
            assert result == {"deleted": created["id"]}

            listing = asyncio.run(srv.api_list_sessions())
            assert len(listing["sessions"]) == 0

    def test_delete_nonexistent(self, tmp_path: t.Any) -> None:
        """DELETE /api/sessions/{id} for unknown ID returns error."""
        with _server_state(tmp_path):
            result = asyncio.run(srv.api_delete_session("s-nonexistent"))
            assert result == {"error": "session not found"}

    def test_set_label(self, tmp_path: t.Any) -> None:
        """PUT /api/sessions/{id}/label updates the label."""
        with _server_state(tmp_path):
            created = asyncio.run(srv.api_create_session({"label": "Old"}))
            result = asyncio.run(srv.api_set_label(created["id"], {"label": "New"}))
            assert result["label"] == "New"

    def test_set_label_empty_rejected(self, tmp_path: t.Any) -> None:
        """PUT /api/sessions/{id}/label with empty label returns error."""
        with _server_state(tmp_path):
            created = asyncio.run(srv.api_create_session({"label": "Test"}))
            result = asyncio.run(srv.api_set_label(created["id"], {"label": ""}))
            assert result == {"error": "label is required"}

    def test_create_paper_binds_complete_project(self, tmp_path: t.Any) -> None:
        """Paper creation publishes files and session metadata together."""
        with _server_state(tmp_path) as (_, svc):
            created = asyncio.run(svc.create_session(label="Blank", model="m"))

            with (
                patch("backend.server._rebuild_agent", new_callable=AsyncMock),
                patch("backend.server._restart_pdf_watcher", new_callable=AsyncMock),
            ):
                result = asyncio.run(
                    srv.api_create_paper_for_session(
                        created["id"], {"title": "New Paper"}
                    )
                )

            paper_dir = result["paper_dir"]
            assert os.path.isfile(os.path.join(paper_dir, "paper.yaml"))
            assert os.path.isfile(os.path.join(paper_dir, "main.tex"))
            session = asyncio.run(svc.get_session(created["id"]))
            assert session is not None
            assert session["paper_dir"] == os.path.realpath(paper_dir)
            assert session["label"] == "New Paper"

    def test_create_paper_removes_directory_when_binding_fails(
        self, tmp_path: t.Any
    ) -> None:
        """A database binding failure must not leave an orphaned paper."""
        with _server_state(tmp_path) as (_, svc):
            created = asyncio.run(svc.create_session(label="Blank", model="m"))

            with patch.object(
                svc,
                "set_paper_and_label",
                new=AsyncMock(side_effect=RuntimeError("database unavailable")),
            ):
                result = asyncio.run(
                    srv.api_create_paper_for_session(
                        created["id"], {"title": "Orphan Candidate"}
                    )
                )

            assert "Failed to bind" in result["error"]
            assert os.listdir(tmp_path / "papers") == []
            session = asyncio.run(svc.get_session(created["id"]))
            assert session is not None
            assert session["paper_dir"] is None

    def test_create_paper_keeps_directory_after_ambiguous_database_error(
        self, tmp_path: t.Any
    ) -> None:
        """A confirmed database commit must not trigger filesystem rollback."""
        with _server_state(tmp_path) as (_, svc):
            created = asyncio.run(svc.create_session(label="Blank", model="m"))
            real_bind = svc.set_paper_and_label

            async def commit_then_raise(
                session_id: str, paper_dir: str, label: str
            ) -> None:
                await real_bind(session_id, paper_dir, label)
                raise RuntimeError("connection failed after commit")

            with (
                patch.object(
                    svc,
                    "set_paper_and_label",
                    new=AsyncMock(side_effect=commit_then_raise),
                ),
                patch("backend.server._rebuild_agent", new_callable=AsyncMock),
                patch("backend.server._restart_pdf_watcher", new_callable=AsyncMock),
            ):
                result = asyncio.run(
                    srv.api_create_paper_for_session(
                        created["id"], {"title": "Committed Paper"}
                    )
                )

            assert os.path.isdir(result["paper_dir"])
            session = asyncio.run(svc.get_session(created["id"]))
            assert session is not None
            assert session["paper_dir"] == os.path.realpath(result["paper_dir"])

    def test_delete_cleans_up_runtime_state(self, tmp_path: t.Any) -> None:
        """Deleting a session removes per-session runtime dicts."""
        with _server_state(tmp_path):
            created = asyncio.run(srv.api_create_session({"label": "Test"}))
            sid = created["id"]
            srv._agents[sid] = MagicMock()
            srv._locks[sid] = asyncio.Lock()
            srv._custom_pdfs[sid] = "/tmp/fake.pdf"

            asyncio.run(srv.api_delete_session(sid))

            assert sid not in srv._agents
            assert sid not in srv._locks
            assert sid not in srv._custom_pdfs

    def test_delete_cancels_active_turn_before_removing_session(
        self, tmp_path: t.Any
    ) -> None:
        """Deleting a session stops its turn before deleting persisted state."""
        with _server_state(tmp_path) as (db, svc):
            created = asyncio.run(svc.create_session(label="Busy", model="m"))
            sid = created["id"]

            async def _run() -> None:
                started = asyncio.Event()

                async def blocking_turn(*_a: t.Any, **_kw: t.Any) -> None:
                    started.set()
                    await asyncio.Event().wait()

                with patch("backend.server._run_agent_turn", side_effect=blocking_turn):
                    task = srv._dispatch(db, svc, sid, "work")
                    await started.wait()
                    result = await srv.api_delete_session(sid)

                assert result == {"deleted": sid}
                assert task.done()
                assert await svc.get_session(sid) is None

            asyncio.run(_run())


# ---------------------------------------------------------------------------
# Model swap — _rebuild_agent via api_set_model
# ---------------------------------------------------------------------------


class TestModelSwap:
    """Test model swapping preserves conversation context and emits events."""

    def _make_session_with_agent(
        self, db: Database, svc: SessionService, tmp_path: t.Any
    ) -> dict[str, t.Any]:
        """Create a session with an agent that has conversation history."""
        import rigging as rg

        paper_dir = str(tmp_path / "papers" / "test-paper")
        os.makedirs(paper_dir, exist_ok=True)
        (tmp_path / "papers" / "test-paper" / "paper.yaml").write_text(
            'title: "Test"\n'
        )
        session = asyncio.run(
            svc.create_session(
                label="Test",
                paper_dir=paper_dir,
                model="old-model",
            )
        )
        agent = create_agent("old-model", paper_dir, session_id=session["id"])
        agent.thread.messages = [
            rg.Message("user", "write an abstract"),
            rg.Message("assistant", "Here is a draft abstract."),
        ]
        srv._agents[session["id"]] = agent
        return session

    def test_preserves_thread_messages(self, tmp_path: t.Any) -> None:
        """Model swap must transfer conversation history to the new agent."""
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_agent(db, svc, tmp_path)
            sid = session["id"]
            old_messages = list(srv._agents[sid].thread.messages)

            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))

            new_agent = srv._agents[sid]
            assert len(new_agent.thread.messages) == len(old_messages)
            for old, new in zip(old_messages, new_agent.thread.messages):
                assert old.role == new.role
                assert old.content == new.content

    def test_restores_persisted_thread_when_agent_is_not_cached(
        self, tmp_path: t.Any
    ) -> None:
        """A post-restart rebuild must restore history from SQLite."""
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_agent(db, svc, tmp_path)
            sid = session["id"]
            expected = list(srv._agents[sid].thread.messages)
            asyncio.run(srv._save_thread(db, sid))
            srv._agents.pop(sid)

            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))

            rebuilt = srv._agents[sid]
            assert [message.model_dump() for message in rebuilt.thread.messages] == [
                message.model_dump() for message in expected
            ]
            persisted = asyncio.run(srv._load_thread(db, sid))
            assert persisted is not None
            assert [message.model_dump() for message in persisted] == [
                message.model_dump() for message in expected
            ]

    def test_rebuild_with_no_persisted_thread_stays_empty(
        self, tmp_path: t.Any
    ) -> None:
        """A genuinely new session rebuilds without manufacturing history."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="New", model="old-model"))
            sid = session["id"]

            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))

            assert srv._agents[sid].thread.messages == []
            assert asyncio.run(srv._load_thread(db, sid)) == []

    def test_corrupt_persisted_thread_is_not_overwritten(self, tmp_path: t.Any) -> None:
        """Unreadable history remains stored instead of being replaced by []."""
        corrupt = [{"not": "a rigging message"}]
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Old", model="old-model"))
            sid = session["id"]
            asyncio.run(db.set_meta(srv._thread_key(sid), corrupt))

            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))

            assert srv._agents[sid].thread.messages == []
            assert asyncio.run(db.get_meta(srv._thread_key(sid))) == corrupt

    def test_failed_lazy_restore_then_rebuild_does_not_overwrite(
        self, tmp_path: t.Any
    ) -> None:
        """A cached fallback agent must not erase unreadable persisted data."""
        corrupt = [{"not": "a rigging message"}]
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Old", model="old-model"))
            sid = session["id"]
            asyncio.run(db.set_meta(srv._thread_key(sid), corrupt))

            asyncio.run(srv._get_or_create_agent(session, db))
            assert sid in srv._thread_restore_failures
            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))

            assert asyncio.run(db.get_meta(srv._thread_key(sid))) == corrupt

    def test_clear_history_unlocks_saves_after_restore_failure(
        self, tmp_path: t.Any
    ) -> None:
        """Explicit history clearing removes protection and permits new saves."""
        import rigging as rg

        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Old", model="old-model"))
            sid = session["id"]
            asyncio.run(
                db.set_meta(srv._thread_key(sid), [{"not": "a rigging message"}])
            )
            asyncio.run(srv._get_or_create_agent(session, db))

            asyncio.run(srv.api_clear_history(sid))
            assert sid not in srv._thread_restore_failures
            srv._agents[sid].thread.messages = [rg.Message("user", "fresh start")]
            asyncio.run(srv._save_thread(db, sid))

            restored = asyncio.run(srv._load_thread(db, sid))
            assert restored is not None
            assert [message.content for message in restored] == ["fresh start"]

    def test_replaces_agent_object(self, tmp_path: t.Any) -> None:
        """The agent object must be replaced, not reused."""
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_agent(db, svc, tmp_path)
            sid = session["id"]
            old_agent = srv._agents[sid]

            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))
            assert srv._agents[sid] is not old_agent

    def test_emits_status_event(self, tmp_path: t.Any) -> None:
        """A status event recording the model change must be persisted."""
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_agent(db, svc, tmp_path)
            sid = session["id"]

            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))

            events = asyncio.run(db.get_events(sid, kinds=["status"]))
            assert len(events) == 1
            assert "new-model" in events[0]["payload"]["content"]

    def test_returns_error_for_empty_model(self, tmp_path: t.Any) -> None:
        """Empty model string must be rejected."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="X", model="m"))
            result = asyncio.run(srv.api_set_model(session["id"], {"model": ""}))
            assert result == {"error": "model is required"}

    def test_returns_error_for_nonexistent_session(self, tmp_path: t.Any) -> None:
        """Swapping model on unknown session must return error."""
        with _server_state(tmp_path):
            result = asyncio.run(srv.api_set_model("s-ghost", {"model": "m"}))
            assert result == {"error": "session not found"}

    def test_updates_persisted_model(self, tmp_path: t.Any) -> None:
        """The model field in the DB must be updated."""
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_agent(db, svc, tmp_path)
            sid = session["id"]

            asyncio.run(srv.api_set_model(sid, {"model": "new-model"}))

            updated = asyncio.run(svc.get_session(sid))
            assert updated is not None
            assert updated["model"] == "new-model"


# ---------------------------------------------------------------------------
# update_paper_title endpoint
# ---------------------------------------------------------------------------


class TestUpdatePaperTitle:
    """Test PUT /api/sessions/{id}/paper-title."""

    @pytest.fixture(autouse=True)
    def _mock_pdf_build(self) -> t.Iterator[AsyncMock]:
        with patch("backend.server._build_title_pdf", new_callable=AsyncMock) as build:
            build.return_value = None
            yield build

    def _make_session_with_paper(
        self,
        svc: SessionService,
        tmp_path: t.Any,
        yaml_content: str = 'title: "Old Title"\ntemplate: article\n',
    ) -> dict[str, t.Any]:
        paper_dir = str(tmp_path / "papers" / "t")
        os.makedirs(paper_dir, exist_ok=True)
        with open(os.path.join(paper_dir, "paper.yaml"), "w") as f:
            f.write(yaml_content)
        template_main = os.path.join(
            os.path.dirname(__file__),
            "..",
            "templates",
            "article",
            "main.tex",
        )
        shutil.copy2(template_main, os.path.join(paper_dir, "main.tex"))
        return asyncio.run(
            svc.create_session(
                label="Old Title",
                paper_dir=paper_dir,
                model="m",
            )
        )

    def test_normal_update(self, tmp_path: t.Any, _mock_pdf_build: AsyncMock) -> None:
        """Updating title changes paper.yaml and session label."""
        import yaml

        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            result = asyncio.run(
                srv.api_update_paper_title(
                    session["id"],
                    {"title": "New Title"},
                )
            )
            assert result == {"title": "New Title"}

            yaml_path = os.path.join(session["paper_dir"], "paper.yaml")
            data = yaml.safe_load(open(yaml_path).read())
            assert data["title"] == "New Title"
            assert data["template"] == "article"
            main_content = open(os.path.join(session["paper_dir"], "main.tex")).read()
            assert r"\newcommand{\papertitle}{New Title}" in main_content

            updated = asyncio.run(svc.get_session(session["id"]))
            assert updated is not None
            assert updated["label"] == "New Title"
            _mock_pdf_build.assert_awaited_once_with(session["paper_dir"])

    def test_idempotent_update_repairs_stale_main_tex(self, tmp_path: t.Any) -> None:
        """Saving the same YAML title still synchronizes stale generated source."""
        with _server_state(tmp_path) as (_, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            main_path = os.path.join(session["paper_dir"], "main.tex")
            assert "Old Title" not in open(main_path).read()

            result = asyncio.run(
                srv.api_update_paper_title(session["id"], {"title": "Old Title"})
            )

            assert result == {"title": "Old Title"}
            assert r"\newcommand{\papertitle}{Old Title}" in open(main_path).read()

    def test_sync_failure_restores_sources_and_label(self, tmp_path: t.Any) -> None:
        """A sync error must leave YAML, TeX, and SQLite unchanged."""
        with _server_state(tmp_path) as (_, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            yaml_path = os.path.join(session["paper_dir"], "paper.yaml")
            main_path = os.path.join(session["paper_dir"], "main.tex")
            before_yaml = open(yaml_path).read()
            before_main = open(main_path).read()

            with patch(
                "backend.server._sync_title_stage",
                new=AsyncMock(side_effect=RuntimeError("sync failed")),
            ):
                result = asyncio.run(
                    srv.api_update_paper_title(
                        session["id"],
                        {"title": "New Title"},
                    )
                )

            assert "Failed to synchronize" in result["error"]
            assert open(yaml_path).read() == before_yaml
            assert open(main_path).read() == before_main
            updated = asyncio.run(svc.get_session(session["id"]))
            assert updated is not None
            assert updated["label"] == "Old Title"

    def test_database_failure_restores_synchronized_sources(
        self, tmp_path: t.Any
    ) -> None:
        """A failed label commit rolls YAML and main.tex back together."""
        with _server_state(tmp_path) as (_, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            yaml_path = os.path.join(session["paper_dir"], "paper.yaml")
            main_path = os.path.join(session["paper_dir"], "main.tex")
            before_yaml = open(yaml_path).read()
            before_main = open(main_path).read()

            with patch.object(
                svc,
                "set_label",
                new=AsyncMock(side_effect=RuntimeError("database unavailable")),
            ):
                result = asyncio.run(
                    srv.api_update_paper_title(
                        session["id"],
                        {"title": "New Title"},
                    )
                )

            assert "Failed to update session title" in result["error"]
            assert open(yaml_path).read() == before_yaml
            assert open(main_path).read() == before_main

    def test_database_failure_does_not_publish_sync_side_files(
        self, tmp_path: t.Any
    ) -> None:
        """Staged sync additions must not leak into a rolled-back live paper."""
        manifest = (
            'title: "Old Title"\n'
            "template: article\n"
            "sections:\n"
            "  - slug: 01_new\n"
            "    title: New Section\n"
        )
        with _server_state(tmp_path) as (_, svc):
            session = self._make_session_with_paper(
                svc,
                tmp_path,
                yaml_content=manifest,
            )
            section_path = os.path.join(session["paper_dir"], "section", "01_new.tex")

            with patch.object(
                svc,
                "set_label",
                new=AsyncMock(side_effect=RuntimeError("database unavailable")),
            ):
                result = asyncio.run(
                    srv.api_update_paper_title(
                        session["id"],
                        {"title": "New Title"},
                    )
                )

            assert "Failed to update session title" in result["error"]
            assert not os.path.exists(section_path)

    def test_build_failure_keeps_title_and_returns_warning(
        self, tmp_path: t.Any
    ) -> None:
        """Unrelated LaTeX errors do not discard a valid source update."""
        with _server_state(tmp_path) as (_, svc):
            session = self._make_session_with_paper(svc, tmp_path)

            with patch(
                "backend.server._build_title_pdf",
                new=AsyncMock(side_effect=RuntimeError("latex failed")),
            ):
                result = asyncio.run(
                    srv.api_update_paper_title(
                        session["id"],
                        {"title": "New Title"},
                    )
                )

            assert result["title"] == "New Title"
            assert "PDF could not be rebuilt" in result["warning"]
            assert (
                "New Title"
                in open(os.path.join(session["paper_dir"], "main.tex")).read()
            )

    def test_cached_agent_is_rebuilt_with_new_title(self, tmp_path: t.Any) -> None:
        """A cached agent refreshes paper context without losing its thread."""
        import rigging as rg

        with _server_state(tmp_path) as (_, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            sid = session["id"]
            old_agent = create_agent("m", session["paper_dir"], session_id=sid)
            old_agent.thread.messages = [rg.Message("user", "remember this")]
            srv._agents[sid] = old_agent
            try:
                result = asyncio.run(
                    srv.api_update_paper_title(sid, {"title": "New Title"})
                )

                assert result == {"title": "New Title"}
                assert srv._agents[sid] is not old_agent
                assert "New Title" in (srv._agents[sid].instructions or "")
                assert [m.content for m in srv._agents[sid].thread.messages] == [
                    "remember this"
                ]
            finally:
                srv._agents.pop(sid, None)

    @pytest.mark.parametrize(
        "title",
        [
            'He said "hello"',
            r"C:\Users\me",
            "Colons: tricky",
            "Hash # sign",
        ],
        ids=["quotes", "backslashes", "colons", "hash"],
    )
    def test_special_chars_roundtrip(self, tmp_path: t.Any, title: str) -> None:
        """Titles with YAML-special characters survive write/read."""
        import yaml

        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            result = asyncio.run(
                srv.api_update_paper_title(
                    session["id"],
                    {"title": title},
                )
            )
            assert result == {"title": title}
            data = yaml.safe_load(
                open(os.path.join(session["paper_dir"], "paper.yaml")).read()
            )
            assert data["title"] == title

    def test_control_chars_stripped(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            result = asyncio.run(
                srv.api_update_paper_title(
                    session["id"],
                    {"title": "A\x00B\nC"},
                )
            )
            assert result == {"title": "A B C"}

    @pytest.mark.parametrize("title", ["", "   "])
    def test_blank_title_rejected(self, tmp_path: t.Any, title: str) -> None:
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            result = asyncio.run(
                srv.api_update_paper_title(
                    session["id"],
                    {"title": title},
                )
            )
            assert result == {"error": "title is required"}

    def test_missing_yaml(self, tmp_path: t.Any) -> None:
        """Session with paper_dir but no paper.yaml returns error."""
        with _server_state(tmp_path) as (db, svc):
            paper_dir = str(tmp_path / "papers" / "no-yaml")
            os.makedirs(paper_dir, exist_ok=True)
            session = {
                "id": "s-invalid",
                "label": "X",
                "paper_dir": paper_dir,
                "model": "m",
            }
            asyncio.run(db.upsert_session(session))
            result = asyncio.run(
                srv.api_update_paper_title(
                    session["id"],
                    {"title": "X"},
                )
            )
            assert result == {"error": "paper.yaml not found"}

    def test_missing_main_tex(self, tmp_path: t.Any) -> None:
        """A paper without generated source is rejected before changing YAML."""
        with _server_state(tmp_path) as (_, svc):
            session = self._make_session_with_paper(svc, tmp_path)
            main_path = os.path.join(session["paper_dir"], "main.tex")
            os.unlink(main_path)

            result = asyncio.run(
                srv.api_update_paper_title(session["id"], {"title": "New Title"})
            )

            assert result == {"error": "main.tex not found"}
            assert (
                "Old Title"
                in open(os.path.join(session["paper_dir"], "paper.yaml")).read()
            )

    def test_session_without_paper(self, tmp_path: t.Any) -> None:
        """Session with no paper_dir returns error."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Blank", model="m"))
            result = asyncio.run(
                srv.api_update_paper_title(
                    session["id"],
                    {"title": "X"},
                )
            )
            assert result == {"error": "session has no paper"}

    def test_nonexistent_session(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path):
            result = asyncio.run(
                srv.api_update_paper_title(
                    "s-ghost",
                    {"title": "X"},
                )
            )
            assert result == {"error": "session not found"}

    def test_missing_title_field_in_yaml(self, tmp_path: t.Any) -> None:
        """paper.yaml without a title: line returns error."""
        with _server_state(tmp_path) as (db, svc):
            session = self._make_session_with_paper(
                svc,
                tmp_path,
                yaml_content="template: article\n",
            )
            result = asyncio.run(
                srv.api_update_paper_title(
                    session["id"],
                    {"title": "X"},
                )
            )
            assert result == {"error": "Could not find title field in paper.yaml"}


# ---------------------------------------------------------------------------
# Notes endpoints
# ---------------------------------------------------------------------------


class TestNotesEndpoints:
    @staticmethod
    def _create_paper_session(svc: SessionService, tmp_path: t.Any) -> dict[str, t.Any]:
        paper_dir = tmp_path / "papers" / "notes-paper"
        paper_dir.mkdir(parents=True)
        (paper_dir / "paper.yaml").write_text('title: "Notes"\n')
        return asyncio.run(
            svc.create_session(
                label="Notes",
                paper_dir=str(paper_dir),
                model="m",
            )
        )

    def test_missing_session_rejected(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path):
            assert asyncio.run(srv.api_get_notes("missing")) == {
                "error": "session not found"
            }
            assert asyncio.run(srv.api_save_notes("missing", {"content": "x"})) == {
                "error": "session not found"
            }

    def test_session_without_paper_rejected(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path) as (_, svc):
            session = asyncio.run(svc.create_session(label="Blank", model="m"))
            assert asyncio.run(srv.api_get_notes(session["id"])) == {
                "error": "session has no paper"
            }
            assert asyncio.run(srv.api_save_notes(session["id"], {"content": "x"})) == {
                "error": "session has no paper"
            }

    def test_missing_file_is_empty_and_saved_content_roundtrips(
        self, tmp_path: t.Any
    ) -> None:
        with _server_state(tmp_path) as (_, svc):
            session = self._create_paper_session(svc, tmp_path)
            sid = session["id"]

            assert asyncio.run(srv.api_get_notes(sid)) == {"content": ""}
            assert asyncio.run(
                srv.api_save_notes(sid, {"content": "first\nsecond\n"})
            ) == {"status": "saved"}
            assert asyncio.run(srv.api_get_notes(sid)) == {"content": "first\nsecond\n"}

    def test_non_string_content_does_not_overwrite_notes(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path) as (_, svc):
            session = self._create_paper_session(svc, tmp_path)
            notes_path = os.path.join(session["paper_dir"], "notes.md")
            with open(notes_path, "w", encoding="utf-8") as notes_file:
                notes_file.write("keep me")

            result = asyncio.run(
                srv.api_save_notes(session["id"], {"content": ["invalid"]})
            )

            assert result == {"error": "content must be a string"}
            with open(notes_path, encoding="utf-8") as notes_file:
                assert notes_file.read() == "keep me"

    def test_save_uses_atomic_writer(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path) as (_, svc):
            session = self._create_paper_session(svc, tmp_path)
            expected_path = os.path.join(session["paper_dir"], "notes.md")

            with patch("backend.server._atomic_write_text") as atomic_write:
                result = asyncio.run(
                    srv.api_save_notes(session["id"], {"content": "safe"})
                )

            assert result == {"status": "saved"}
            atomic_write.assert_called_once_with(expected_path, "safe")


# ---------------------------------------------------------------------------
# upload_pdf temp file cleanup
# ---------------------------------------------------------------------------


class TestUploadPdfCleanup:
    """Test that upload-pdf properly manages _custom_pdfs per session."""

    def test_deletes_previous_upload(self, tmp_path: t.Any) -> None:
        """Uploading a new PDF should delete the previous al-upload-* temp file."""
        old_tmp = tmp_path / "al-upload-old.pdf"
        old_tmp.write_bytes(b"%PDF-old")
        srv._custom_pdfs["s-test"] = str(old_tmp)
        srv._uploaded_pdfs.add(str(old_tmp))

        mock_file = MagicMock()
        mock_file.filename = "new.pdf"
        mock_file.read = AsyncMock(return_value=b"%PDF-new")

        with patch("backend.server.tempfile.NamedTemporaryFile") as mock_ntf:
            new_tmp = tmp_path / "al-upload-new.pdf"
            mock_obj = MagicMock()
            mock_obj.name = str(new_tmp)
            mock_obj.__enter__.return_value = mock_obj
            mock_ntf.return_value = mock_obj

            with patch("backend.server._pdf_clients", set()):
                asyncio.run(srv.api_upload_pdf("s-test", mock_file))

        assert not old_tmp.exists(), "Previous upload should be deleted"
        assert srv._custom_pdfs["s-test"] == str(new_tmp)

    def test_does_not_delete_user_pdf(self, tmp_path: t.Any) -> None:
        """PDFs set via agent tools (not uploads) must NOT be deleted."""
        user_pdf = tmp_path / "my-paper.pdf"
        user_pdf.write_bytes(b"%PDF-user")
        srv._custom_pdfs["s-test2"] = str(user_pdf)

        mock_file = MagicMock()
        mock_file.filename = "upload.pdf"
        mock_file.read = AsyncMock(return_value=b"%PDF-upload")

        with patch("backend.server.tempfile.NamedTemporaryFile") as mock_ntf:
            new_tmp = tmp_path / "al-upload-new.pdf"
            mock_obj = MagicMock()
            mock_obj.name = str(new_tmp)
            mock_obj.__enter__.return_value = mock_obj
            mock_ntf.return_value = mock_obj

            with patch("backend.server._pdf_clients", set()):
                asyncio.run(srv.api_upload_pdf("s-test2", mock_file))

        assert user_pdf.exists(), "User PDF must not be deleted"

    def test_isolates_sessions(self, tmp_path: t.Any) -> None:
        """Upload to one session must not affect another session's PDF."""
        other_pdf = tmp_path / "al-upload-other.pdf"
        other_pdf.write_bytes(b"%PDF-other")
        srv._custom_pdfs["s-other"] = str(other_pdf)

        mock_file = MagicMock()
        mock_file.filename = "new.pdf"
        mock_file.read = AsyncMock(return_value=b"%PDF-new")

        with patch("backend.server.tempfile.NamedTemporaryFile") as mock_ntf:
            mock_obj = MagicMock()
            mock_obj.name = str(tmp_path / "al-upload-new.pdf")
            mock_obj.__enter__.return_value = mock_obj
            mock_ntf.return_value = mock_obj

            with patch("backend.server._pdf_clients", set()):
                asyncio.run(srv.api_upload_pdf("s-mine", mock_file))

        assert other_pdf.exists(), "Other session's PDF must not be deleted"
        assert srv._custom_pdfs["s-other"] == str(other_pdf)

    def test_failed_read_removes_staged_file_and_preserves_viewer(
        self, tmp_path: t.Any
    ) -> None:
        """A failed upload must not leak a file or replace the current PDF."""
        current_pdf = tmp_path / "current.pdf"
        current_pdf.write_bytes(b"%PDF-current")
        srv._custom_pdfs["s-failed"] = str(current_pdf)

        mock_file = MagicMock()
        mock_file.filename = "broken.pdf"
        mock_file.read = AsyncMock(side_effect=RuntimeError("read failed"))
        named_tempfile = tempfile.NamedTemporaryFile

        def create_local_tempfile(**kwargs: t.Any) -> t.Any:
            return named_tempfile(dir=tmp_path, **kwargs)

        with patch(
            "backend.server.tempfile.NamedTemporaryFile",
            side_effect=create_local_tempfile,
        ):
            with pytest.raises(RuntimeError, match="read failed"):
                asyncio.run(srv.api_upload_pdf("s-failed", mock_file))

        assert srv._custom_pdfs["s-failed"] == str(current_pdf)
        assert current_pdf.exists()
        assert list(tmp_path.glob("al-upload-*.pdf")) == []


# ---------------------------------------------------------------------------
# Chat history — clear and event persistence
# ---------------------------------------------------------------------------


class TestChatHistory:
    """Test DELETE /api/sessions/{id}/history and event replay."""

    def test_clear_rebuilds_agent_if_exists(self, tmp_path: t.Any) -> None:
        """Clearing history rebuilds the in-memory agent (fresh context)."""
        with _server_state(tmp_path) as (db, svc):
            paper_dir = str(tmp_path / "papers" / "p")
            os.makedirs(paper_dir, exist_ok=True)
            (tmp_path / "papers" / "p" / "paper.yaml").write_text('title: "T"\n')
            session = asyncio.run(
                svc.create_session(
                    label="T",
                    paper_dir=paper_dir,
                    model="m",
                )
            )
            sid = session["id"]
            old_agent = create_agent("m", paper_dir, session_id=sid)
            srv._agents[sid] = old_agent

            asyncio.run(srv.api_clear_history(sid))

            assert srv._agents[sid] is not old_agent

    def test_clear_does_not_error_without_agent(self, tmp_path: t.Any) -> None:
        """Clearing history when no agent is cached should not error."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]
            assert sid not in srv._agents
            result = asyncio.run(srv.api_clear_history(sid))
            assert result == {"status": "cleared"}

    def test_clear_one_does_not_affect_other(self, tmp_path: t.Any) -> None:
        """Clearing one session's history must not touch another's."""
        with _server_state(tmp_path) as (db, svc):
            s1 = asyncio.run(svc.create_session(label="A", model="m"))
            s2 = asyncio.run(svc.create_session(label="B", model="m"))
            asyncio.run(db.append_event(s1["id"], "user_message", {"content": "s1"}))
            asyncio.run(db.append_event(s2["id"], "user_message", {"content": "s2"}))

            s2_count_before = len(asyncio.run(db.get_events(s2["id"])))
            result = asyncio.run(srv.api_clear_history(s1["id"]))

            assert result == {"status": "cleared"}
            assert len(asyncio.run(db.get_events(s1["id"]))) == 0
            assert len(asyncio.run(db.get_events(s2["id"]))) == s2_count_before


# ---------------------------------------------------------------------------
# _dispatch / per-session task management / cancel
# ---------------------------------------------------------------------------


class TestDispatchAndCancel:
    """Test _dispatch task lifecycle and per-session cancel."""

    def test_dispatch_removes_task_on_completion(self, tmp_path: t.Any) -> None:
        """Task is removed from _session_tasks after it completes."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]

            async def _run() -> None:
                with patch("backend.server._run_agent_turn", new_callable=AsyncMock):
                    task = srv._dispatch(db, svc, sid, "hello")
                    await task
                assert sid not in srv._session_tasks

            asyncio.run(_run())

    def test_earlier_dispatch_does_not_untrack_queued_task(
        self, tmp_path: t.Any
    ) -> None:
        """Completing an earlier turn leaves the queued turn cancellable."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]

            async def _run() -> None:
                first_started = asyncio.Event()
                release_first = asyncio.Event()
                release_second = asyncio.Event()
                calls = 0

                async def queued_turn(*_a: t.Any, **_kw: t.Any) -> None:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        first_started.set()
                        await release_first.wait()
                    else:
                        await release_second.wait()

                with patch("backend.server._run_agent_turn", side_effect=queued_turn):
                    first = srv._dispatch(db, svc, sid, "first")
                    await first_started.wait()
                    second = srv._dispatch(db, svc, sid, "second")
                    assert srv._session_tasks[sid] is second
                    assert second is not first
                    release_first.set()
                    await first
                    await asyncio.sleep(0)

                    assert srv._session_tasks[sid] is second

                    second.cancel()
                    with suppress(asyncio.CancelledError):
                        await second
                    await asyncio.sleep(0)
                    assert sid not in srv._session_tasks

            asyncio.run(_run())

    def test_cancel_helper_stops_running_and_queued_turns(
        self, tmp_path: t.Any
    ) -> None:
        """Session cancellation covers both the active and queued tasks."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]

            async def _run() -> None:
                started = asyncio.Event()

                async def blocking_turn(*_a: t.Any, **_kw: t.Any) -> None:
                    started.set()
                    await asyncio.Event().wait()

                with patch("backend.server._run_agent_turn", side_effect=blocking_turn):
                    first = srv._dispatch(db, svc, sid, "first")
                    await started.wait()
                    second = srv._dispatch(db, svc, sid, "second")
                    await srv._cancel_session_task(sid)

                assert first.done()
                assert second.done()
                assert sid not in srv._session_task_groups

            asyncio.run(_run())


# ---------------------------------------------------------------------------
# _emit_event — persistence and WebSocket routing
# ---------------------------------------------------------------------------


class TestEmitEvent:
    """Test _emit_event persistence and per-session WebSocket delivery."""

    def test_lifecycle_event_is_live_only_by_default(self, tmp_path: t.Any) -> None:
        """Transient lifecycle events should stream without entering history."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]
            websocket = MagicMock()
            websocket.send_text = AsyncMock()
            srv._conns[sid] = websocket
            try:
                asyncio.run(srv._emit_event(db, sid, "step_start", {"step": 1}))
                assert asyncio.run(db.get_events(sid)) == []
                websocket.send_text.assert_awaited_once()
            finally:
                del srv._conns[sid]

    def test_persisted_text_is_bounded_but_live_event_is_complete(
        self, tmp_path: t.Any
    ) -> None:
        """Persistence limits must not truncate the currently streamed response."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]
            websocket = MagicMock()
            websocket.send_text = AsyncMock()
            srv._conns[sid] = websocket
            content = "é" * 20
            try:
                with patch.object(srv, "MAX_REPLAY_TEXT_BYTES", 16):
                    asyncio.run(
                        srv._emit_event(db, sid, "generation", {"content": content})
                    )

                stored = asyncio.run(db.get_events(sid))[0]["payload"]
                assert len(stored["content"].encode("utf-8")) <= 16
                assert stored["truncated"] is True
                sent = json.loads(websocket.send_text.await_args.args[0])
                assert sent["content"] == content
            finally:
                del srv._conns[sid]

    def test_persisted_image_event_omits_raw_data(self, tmp_path: t.Any) -> None:
        """Replay keeps an attachment marker while the live event has its preview."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]
            websocket = MagicMock()
            websocket.send_text = AsyncMock()
            srv._conns[sid] = websocket
            payload = {
                "content": "transcribe",
                "images": [{"data": "sensitive-base64", "media_type": "image/png"}],
            }
            try:
                asyncio.run(srv._emit_event(db, sid, "user_message", payload))
                stored = asyncio.run(db.get_events(sid))[0]["payload"]
                sent = json.loads(websocket.send_text.await_args.args[0])
            finally:
                del srv._conns[sid]

            assert stored == {"content": "transcribe", "image_count": 1}
            assert sent["images"] == payload["images"]

    def test_websocket_error_swallowed(self, tmp_path: t.Any) -> None:
        """WebSocket send errors are caught, not propagated."""
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]
            mock_ws = MagicMock()
            mock_ws.send_text = AsyncMock(
                side_effect=RuntimeError("disconnected"),
            )
            srv._conns[sid] = mock_ws

            try:
                asyncio.run(
                    srv._emit_event(
                        db,
                        sid,
                        "error",
                        {"message": "oops"},
                    )
                )
                events = asyncio.run(db.get_events(sid, kinds=["error"]))
                assert len(events) == 1
            finally:
                del srv._conns[sid]

    def test_routes_to_correct_session(self, tmp_path: t.Any) -> None:
        """Events are sent only to the WebSocket for that session, with correct JSON."""
        import json

        with _server_state(tmp_path) as (db, svc):
            s1 = asyncio.run(svc.create_session(label="A", model="m"))
            s2 = asyncio.run(svc.create_session(label="B", model="m"))
            ws1 = MagicMock()
            ws1.send_text = AsyncMock()
            ws2 = MagicMock()
            ws2.send_text = AsyncMock()
            srv._conns[s1["id"]] = ws1
            srv._conns[s2["id"]] = ws2

            try:
                asyncio.run(
                    srv._emit_event(
                        db,
                        s1["id"],
                        "generation",
                        {"content": "for s1"},
                    )
                )
                ws1.send_text.assert_called_once()
                ws2.send_text.assert_not_called()

                sent = json.loads(ws1.send_text.call_args[0][0])
                assert sent["session_id"] == s1["id"]
                assert sent["type"] == "generation"
                assert sent["content"] == "for s1"
            finally:
                del srv._conns[s1["id"]]
                del srv._conns[s2["id"]]


class TestBoundedHistoryReplay:
    """Reconnect history must use the bounded query and include stable sequence IDs."""

    def test_resume_requests_bounded_history(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]
            websocket = MagicMock()
            websocket.headers = {"origin": "http://localhost:8420"}
            websocket.accept = AsyncMock()
            websocket.receive_text = AsyncMock(
                side_effect=[
                    json.dumps({"session_id": sid, "type": "resume"}),
                    srv.WebSocketDisconnect(),
                ]
            )
            websocket.send_text = AsyncMock()
            replay = [
                {
                    "seq": 42,
                    "kind": "generation",
                    "ts": "now",
                    "payload": {"content": "hello"},
                }
            ]

            with patch.object(db, "get_events", AsyncMock(return_value=replay)) as get:
                asyncio.run(srv.ws_chat(websocket))

            get.assert_awaited_once_with(
                sid,
                kinds=srv.CHAT_KINDS,
                limit=srv.EVENT_REPLAY_LIMIT,
            )
            sent = json.loads(websocket.send_text.await_args.args[0])
            assert sent["events"] == [
                {"content": "hello", "type": "generation", "seq": 42}
            ]


class TestImageAttachments:
    """Image chat input is bounded, validated, and isolated from agent tools."""

    @pytest.mark.parametrize(
        ("data", "media_type"),
        [
            (b"GIF89a-data", "image/gif"),
            (b"\xff\xd8\xff-data", "image/jpeg"),
            (b"\x89PNG\r\n\x1a\n-data", "image/png"),
            (b"RIFF\x04\x00\x00\x00WEBP-data", "image/webp"),
        ],
    )
    def test_accepts_supported_images(self, data: bytes, media_type: str) -> None:
        encoded = base64.b64encode(data).decode("ascii")
        assert srv._validate_images([{"data": encoded, "media_type": media_type}]) == [
            srv.ImageAttachment(data, media_type)
        ]

    @pytest.mark.parametrize(
        "payload",
        [
            [{"data": "!", "media_type": "image/png"}],
            [
                {
                    "data": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
                    "media_type": "image/jpeg",
                }
            ],
            [
                {
                    "data": base64.b64encode(b"<svg/>").decode(),
                    "media_type": "image/svg+xml",
                }
            ],
            [
                {
                    "data": base64.b64encode(b"GIF89a").decode(),
                    "media_type": "image/gif",
                }
            ]
            * (srv.MAX_IMAGE_COUNT + 1),
        ],
    )
    def test_rejects_malformed_or_unsupported_images(
        self, payload: list[dict[str, str]]
    ) -> None:
        with pytest.raises(ValueError):
            srv._validate_images(payload)

    def test_enforces_combined_decoded_size(self) -> None:
        data = b"\x89PNG\r\n\x1a\n"
        encoded = base64.b64encode(data).decode()
        with (
            patch.object(srv, "MAX_IMAGE_TOTAL_BYTES", len(data)),
            patch.object(srv, "MAX_IMAGE_ENCODED_BYTES", len(encoded)),
            pytest.raises(ValueError, match="total limit"),
        ):
            srv._validate_images(
                [
                    {"data": encoded, "media_type": "image/png"},
                    {"data": encoded, "media_type": "image/png"},
                ]
            )

    def test_image_limit_allows_sixteen_mebibytes(self) -> None:
        assert srv.MAX_IMAGE_TOTAL_BYTES == 16 * 1024 * 1024

    def test_websocket_rejection_terminates_turn(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            websocket = MagicMock()
            websocket.headers = {"origin": "http://localhost:8420"}
            websocket.accept = AsyncMock()
            websocket.receive_text = AsyncMock(
                side_effect=[
                    json.dumps(
                        {
                            "session_id": session["id"],
                            "images": [{"data": "!", "media_type": "image/png"}],
                        }
                    ),
                    srv.WebSocketDisconnect(),
                ]
            )
            websocket.send_text = AsyncMock()

            with patch("backend.server._dispatch") as dispatch:
                asyncio.run(srv.ws_chat(websocket))

            dispatch.assert_not_called()
            sent = [
                json.loads(call.args[0]) for call in websocket.send_text.await_args_list
            ]
            assert [event["type"] for event in sent] == ["error", "agent_end"]

    def test_extraction_failure_terminates_and_does_not_persist_bytes(
        self, tmp_path: t.Any
    ) -> None:
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            sid = session["id"]
            websocket = MagicMock()
            websocket.send_text = AsyncMock()
            srv._conns[sid] = websocket
            image = srv.ImageAttachment(b"\x89PNG\r\n\x1a\n", "image/png")
            try:
                with (
                    patch(
                        "backend.server._get_or_create_agent",
                        new_callable=AsyncMock,
                        return_value=MagicMock(),
                    ),
                    patch(
                        "backend.server.extract_image_content",
                        new_callable=AsyncMock,
                        side_effect=RuntimeError("vision failed"),
                    ),
                ):
                    asyncio.run(
                        srv._run_agent_turn(db, svc, sid, "transcribe", [image])
                    )
            finally:
                del srv._conns[sid]

            stored = asyncio.run(db.get_events(sid))
            assert [event["kind"] for event in stored] == [
                "user_message",
                "status",
                "error",
            ]
            assert stored[0]["payload"] == {
                "content": "transcribe",
                "image_count": 1,
            }
            sent = [
                json.loads(call.args[0]) for call in websocket.send_text.await_args_list
            ]
            assert sent[0]["image_count"] == 1
            assert "images" not in sent[0]
            assert sent[-1]["type"] == "agent_end"
            assert sent[-1]["failed"] is True

    def test_main_agent_receives_only_quoted_transcription(
        self, tmp_path: t.Any
    ) -> None:
        with _server_state(tmp_path) as (db, svc):
            session = asyncio.run(svc.create_session(label="Test", model="m"))
            captured: list[str] = []

            @asynccontextmanager
            async def stream(user_input: str) -> t.AsyncIterator[t.Any]:
                captured.append(user_input)

                async def no_events() -> t.AsyncIterator[t.Any]:
                    if False:
                        yield None

                yield no_events()

            agent = MagicMock()
            agent.stream = stream
            raw = b"\x89PNG\r\n\x1a\nsecret-image-bytes"
            with (
                patch(
                    "backend.server._get_or_create_agent",
                    new_callable=AsyncMock,
                    return_value=agent,
                ),
                patch(
                    "backend.server.extract_image_content",
                    new_callable=AsyncMock,
                    return_value="\\[x^2\\]",
                ),
            ):
                asyncio.run(
                    srv._run_agent_turn(
                        db,
                        svc,
                        session["id"],
                        "transcribe",
                        [srv.ImageAttachment(raw, "image/png")],
                    )
                )

            assert len(captured) == 1
            assert isinstance(captured[0], str)
            assert "untrusted" in captured[0]
            assert base64.b64encode(raw).decode() not in captured[0]
            quoted = json.loads(captured[0].splitlines()[-1])
            assert quoted == {
                "source": "isolated_vision_transcription",
                "untrusted": True,
                "content": "\\[x^2\\]",
            }

    def test_image_extraction_uses_direct_tool_free_generation(self) -> None:
        generated = MagicMock()
        generated.message.content = "\\[x^2\\]"
        generator = MagicMock()
        generator.generate_messages = AsyncMock(return_value=[generated])

        with patch("backend.agent.rg.get_generator", return_value=generator):
            result = asyncio.run(
                extract_image_content(
                    "vision-model",
                    "transcribe",
                    [(b"\x89PNG\r\n\x1a\n", "image/png")],
                )
            )

        assert result == "\\[x^2\\]"
        messages = generator.generate_messages.await_args.args[0][0]
        params = generator.generate_messages.await_args.args[1][0]
        assert [message.role for message in messages] == ["system", "user"]
        assert "untrusted" in messages[0].content
        assert params.tools is None
        assert params.max_tokens == 4096
        assert params.timeout == 120


class TestArtifactSnapshots:
    """Artifact events store bounded snapshots outside replay payloads."""

    def test_store_emit_and_fetch_is_session_scoped(self, tmp_path: t.Any) -> None:
        with _server_state(tmp_path) as (db, svc):
            first = asyncio.run(svc.create_session(label="First", model="m"))
            second = asyncio.run(svc.create_session(label="Second", model="m"))
            websocket = MagicMock()
            websocket.send_text = AsyncMock()
            srv._conns[first["id"]] = websocket
            try:
                asyncio.run(
                    srv._store_and_emit_artifact(
                        db,
                        first["id"],
                        filename="report.md",
                        label="Report",
                        path="/paper/report.md",
                        content="snapshot",
                    )
                )
            finally:
                del srv._conns[first["id"]]

            event = asyncio.run(db.get_events(first["id"]))[0]
            assert "content" not in event["payload"]
            artifact_id = event["payload"]["artifact_id"]
            streamed = json.loads(websocket.send_text.await_args.args[0])
            assert streamed["artifact_id"] == artifact_id
            assert "content" not in streamed
            response = asyncio.run(srv.api_get_artifact(first["id"], artifact_id))
            assert response["content"] == "snapshot"
            assert asyncio.run(srv.api_get_artifact(second["id"], artifact_id)) == {
                "error": "artifact not found"
            }
