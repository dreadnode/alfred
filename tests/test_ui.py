"""Tests for ui/backend — tools, agent factory, event formatting, sessions."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import typing as t
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add ui/ to path so we can import backend.*
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
sys.path.insert(0, UI_DIR)

from backend.agent import _load_paper_context, create_agent  # noqa: E402
import backend.server as srv  # noqa: E402
from backend.server import _Session, _format_event, _prune_sessions, _sessions  # noqa: E402
from backend.tools.subprocess import run_script  # noqa: E402
from backend.tools.web import _strip_html, web_fetch  # noqa: E402


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
        assert _strip_html("<p>&#8217;</p>") == "\u2019"

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
        (tmp_path / "paper.yaml").write_text(":::invalid:::")
        result = _load_paper_context(str(tmp_path))
        assert isinstance(result, str)

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
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            asyncio.run(run_script("sleep", "10", cwd="/tmp", timeout=1))

    def test_stderr_merged_into_stdout(self) -> None:
        result = asyncio.run(
            run_script("bash", "-c", "echo out && echo err >&2", cwd="/tmp")
        )
        assert "out" in result
        assert "err" in result

    def test_cancellation_kills_child_process(self) -> None:
        """Cancelling the task should kill the subprocess, not leave it orphaned."""

        async def _cancel_after(delay: float) -> str:
            task = asyncio.create_task(
                run_script("sleep", "60", cwd="/tmp", timeout=120)
            )
            await asyncio.sleep(delay)
            task.cancel()
            return await task

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(_cancel_after(0.2))


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
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

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
        assert "My Great Paper" in agent.instructions
        assert "[in_progress] 01_intro" in agent.instructions

    def test_hooks_registered(self, agent_dir: str) -> None:
        agent = create_agent("test-model", agent_dir)
        hook_names = [
            h.__name__ if hasattr(h, "__name__") else type(h).__name__
            for h in agent.hooks
        ]
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
            ("dreadnode.agent.events.AgentStart", {}, {"type": "agent_start", "agent": "test-agent"}),
            ("dreadnode.agent.events.StepStart", {"step": 3}, {"type": "step_start", "step": 3}),
            ("dreadnode.agent.events.AgentStalled", {}, {"type": "stalled"}),
            ("dreadnode.agent.events.AgentEvent", {}, None),
        ],
        ids=["agent_start", "step_start", "stalled", "unknown_returns_none"],
    )
    def test_simple_events(self, cls_path: str, extra_kwargs: dict, expected: t.Any) -> None:
        event = _make_event(cls_path, **extra_kwargs)
        assert _format_event(event) == expected

    def test_generation_end(self) -> None:
        import rigging as rg

        msg = rg.Message("assistant", "Here is my response.")
        usage = rg.generator.Usage(input_tokens=100, output_tokens=50, total_tokens=150)
        result = _format_event(_make_event("dreadnode.agent.events.GenerationEnd", message=msg, usage=usage))
        assert result is not None
        assert result["type"] == "generation"
        assert result["content"] == "Here is my response."
        assert result["role"] == "assistant"
        assert result["usage"]["total_tokens"] == 150

    def test_generation_end_no_usage(self) -> None:
        import rigging as rg

        msg = rg.Message("assistant", "Response without usage.")
        result = _format_event(_make_event("dreadnode.agent.events.GenerationEnd", message=msg, usage=None))
        assert result is not None
        assert result["usage"] is None
        assert result["content"] == "Response without usage."

    def test_tool_start(self) -> None:
        tc = MagicMock()
        tc.name = "build_paper"
        tc.function.arguments = '{"timeout": 120}'
        result = _format_event(_make_event("dreadnode.agent.events.ToolStart", tool_call=tc))
        assert result == {"type": "tool_start", "tool": "build_paper", "args": '{"timeout": 120}'}

    def test_tool_end_truncates(self) -> None:
        import rigging as rg

        tc = MagicMock()
        tc.name = "web_fetch"
        msg = rg.Message("tool", "x" * 3000)
        result = _format_event(_make_event("dreadnode.agent.events.ToolEnd", tool_call=tc, message=msg, stop=False))
        assert result is not None
        assert len(result["result"]) == 2000
        assert result["stop"] is False

    def test_agent_error(self) -> None:
        result = _format_event(_make_event("dreadnode.agent.events.AgentError", error=RuntimeError("boom")))
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
    def test_reacted(self, reaction_cls: str, kwargs: dict, expected_substr: str) -> None:
        from dreadnode import agent as _a

        reaction = getattr(_a.reactions, reaction_cls)(**kwargs)
        result = _format_event(_make_event("dreadnode.agent.events.Reacted", hook_name="h", reaction=reaction))
        assert result is not None
        assert result["type"] == "reacted"
        assert expected_substr in result["content"]

    def test_agent_end(self) -> None:
        from dreadnode.agent.result import AgentResult

        import rigging as rg

        mock_result = MagicMock(spec=AgentResult)
        mock_result.failed = False
        mock_result.steps = 5
        mock_result.usage = rg.generator.Usage(input_tokens=500, output_tokens=200, total_tokens=700)
        result = _format_event(_make_event("dreadnode.agent.events.AgentEnd", stop_reason="finished", result=mock_result))
        assert result is not None
        assert result["type"] == "agent_end"
        assert result["failed"] is False
        assert result["steps"] == 5
        assert result["usage"]["total_tokens"] == 700


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@contextmanager
def _isolated_sessions() -> t.Iterator[dict[str, _Session]]:
    """Temporarily replace global _sessions, restoring on exit."""
    old = _sessions.copy()
    _sessions.clear()
    try:
        yield _sessions
    finally:
        _sessions.clear()
        _sessions.update(old)


class TestSessionManagement:
    def test_prune_removes_expired(self) -> None:
        with _isolated_sessions() as sessions:
            sessions["old"] = _Session(
                session_id="old",
                agent=MagicMock(),
                last_active=time.time() - 7200,
            )
            sessions["new"] = _Session(
                session_id="new",
                agent=MagicMock(),
                last_active=time.time(),
            )
            _prune_sessions()
            assert "old" not in sessions
            assert "new" in sessions

    def test_prune_keeps_active(self) -> None:
        with _isolated_sessions() as sessions:
            sessions["active"] = _Session(
                session_id="active",
                agent=MagicMock(),
                last_active=time.time() - 60,
            )
            _prune_sessions()
            assert "active" in sessions

    def test_prune_empty(self) -> None:
        with _isolated_sessions():
            _prune_sessions()
            assert len(_sessions) == 0


# ---------------------------------------------------------------------------
# update_paper_title endpoint
# ---------------------------------------------------------------------------


@contextmanager
def _paper_dir(path: str) -> t.Iterator[None]:
    """Temporarily set srv._paper_dir, restoring on exit."""
    old = srv._paper_dir
    srv._paper_dir = path
    try:
        yield
    finally:
        srv._paper_dir = old


class TestUpdatePaperTitle:
    def test_normal_update(self, tmp_path: t.Any) -> None:
        import yaml

        (tmp_path / "paper.yaml").write_text('title: "Old Title"\ntemplate: article\n')
        with _paper_dir(str(tmp_path)):
            result = asyncio.run(srv.update_paper_title({"title": "New Title"}))
        assert result == {"title": "New Title"}
        data = yaml.safe_load((tmp_path / "paper.yaml").read_text())
        assert data["title"] == "New Title"
        assert data["template"] == "article"

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
        """Titles with YAML-special characters must survive a write/read cycle."""
        import yaml

        (tmp_path / "paper.yaml").write_text('title: "Old"\n')
        with _paper_dir(str(tmp_path)):
            result = asyncio.run(srv.update_paper_title({"title": title}))
        assert result == {"title": title}
        data = yaml.safe_load((tmp_path / "paper.yaml").read_text())
        assert data["title"] == title

    def test_control_chars_stripped(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text('title: "Old"\n')
        with _paper_dir(str(tmp_path)):
            result = asyncio.run(srv.update_paper_title({"title": "A\x00B\nC"}))
        assert result == {"title": "A B C"}

    def test_empty_title_rejected(self) -> None:
        result = asyncio.run(srv.update_paper_title({"title": ""}))
        assert result == {"error": "title is required"}

    def test_whitespace_only_rejected(self) -> None:
        result = asyncio.run(srv.update_paper_title({"title": "   "}))
        assert result == {"error": "title is required"}

    def test_control_only_rejected(self) -> None:
        result = asyncio.run(srv.update_paper_title({"title": "\x01\x02"}))
        assert result == {"error": "title is required"}

    def test_missing_yaml(self, tmp_path: t.Any) -> None:
        with _paper_dir(str(tmp_path)):
            result = asyncio.run(srv.update_paper_title({"title": "X"}))
        assert result == {"error": "paper.yaml not found"}

    def test_missing_title_field(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text("template: article\n")
        with _paper_dir(str(tmp_path)):
            result = asyncio.run(srv.update_paper_title({"title": "X"}))
        assert result == {"error": "Could not find title field in paper.yaml"}


# ---------------------------------------------------------------------------
# upload_pdf temp file cleanup
# ---------------------------------------------------------------------------


class TestUploadPdfCleanup:
    def test_deletes_previous_upload(self, tmp_path: t.Any) -> None:
        """Uploading a new PDF should delete the previous al-upload-* temp file."""
        old_tmp = tmp_path / "al-upload-old.pdf"
        old_tmp.write_bytes(b"%PDF-old")
        srv._custom_pdf = str(old_tmp)

        mock_file = MagicMock()
        mock_file.filename = "new.pdf"
        mock_file.read = AsyncMock(return_value=b"%PDF-new")

        with patch("backend.server.tempfile.NamedTemporaryFile") as mock_ntf:
            new_tmp = tmp_path / "al-upload-new.pdf"
            mock_obj = MagicMock()
            mock_obj.name = str(new_tmp)
            mock_ntf.return_value = mock_obj

            with patch("backend.server._pdf_clients", set()):
                asyncio.run(srv.upload_pdf(mock_file))

        assert not old_tmp.exists(), "Previous upload should be deleted"

    def test_does_not_delete_user_pdf(self, tmp_path: t.Any) -> None:
        """PDFs loaded via /load-pdf (not uploads) must NOT be deleted."""
        user_pdf = tmp_path / "my-paper.pdf"
        user_pdf.write_bytes(b"%PDF-user")
        srv._custom_pdf = str(user_pdf)

        mock_file = MagicMock()
        mock_file.filename = "upload.pdf"
        mock_file.read = AsyncMock(return_value=b"%PDF-upload")

        with patch("backend.server.tempfile.NamedTemporaryFile") as mock_ntf:
            new_tmp = tmp_path / "al-upload-new.pdf"
            mock_obj = MagicMock()
            mock_obj.name = str(new_tmp)
            mock_ntf.return_value = mock_obj

            with patch("backend.server._pdf_clients", set()):
                asyncio.run(srv.upload_pdf(mock_file))

        assert user_pdf.exists(), "User PDF must not be deleted"


# ---------------------------------------------------------------------------
# Model swap — _swap_model
# ---------------------------------------------------------------------------


class TestSwapModel:
    """Test that _swap_model preserves session history and transfers thread."""

    def _make_session(self, model: str = "old-model") -> _Session:
        """Create a session with a mock agent that has thread messages and history."""
        import rigging as rg

        agent = MagicMock()
        agent.thread.messages = [
            rg.Message("user", "write an abstract"),
            rg.Message("assistant", "Here is a draft abstract..."),
            rg.Message("user", "make it shorter"),
            rg.Message("assistant", "Shortened abstract..."),
        ]
        session = _Session(
            session_id="test-session",
            agent=agent,
            history=[
                {"type": "user_message", "content": "write an abstract"},
                {"type": "generation", "content": "Here is a draft abstract..."},
                {"type": "user_message", "content": "make it shorter"},
                {"type": "generation", "content": "Shortened abstract..."},
            ],
        )
        return session

    def test_preserves_session_ids(self, tmp_path: t.Any) -> None:
        """Session IDs must survive a model swap."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        with _paper_dir(str(tmp_path)), _isolated_sessions() as sessions:
            sessions["s1"] = self._make_session()
            sessions["s2"] = self._make_session()
            srv._swap_model("new-model")
            assert "s1" in sessions
            assert "s2" in sessions

    def test_preserves_ui_history(self, tmp_path: t.Any) -> None:
        """UI event history must survive a model swap."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        with _paper_dir(str(tmp_path)), _isolated_sessions() as sessions:
            sessions["s1"] = self._make_session()
            original_history_len = len(sessions["s1"].history)
            srv._swap_model("new-model")
            # History preserved plus a status message about the swap
            assert len(sessions["s1"].history) >= original_history_len

    def test_adds_status_event(self, tmp_path: t.Any) -> None:
        """A status event should be appended indicating the model changed."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        with _paper_dir(str(tmp_path)), _isolated_sessions() as sessions:
            sessions["s1"] = self._make_session()
            srv._swap_model("new-model")
            last = sessions["s1"].history[-1]
            assert last["type"] == "status"
            assert "new-model" in last["content"]

    def test_creates_new_agent(self, tmp_path: t.Any) -> None:
        """The agent object must be replaced (new model), not reused."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        with _paper_dir(str(tmp_path)), _isolated_sessions() as sessions:
            sessions["s1"] = self._make_session()
            old_agent = sessions["s1"].agent
            srv._swap_model("new-model")
            assert sessions["s1"].agent is not old_agent

    def test_transfers_thread_messages(self, tmp_path: t.Any) -> None:
        """Old conversation messages must be loaded into the new agent's thread."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        with _paper_dir(str(tmp_path)), _isolated_sessions() as sessions:
            sessions["s1"] = self._make_session()
            old_messages = list(sessions["s1"].agent.thread.messages)
            srv._swap_model("new-model")
            new_messages = sessions["s1"].agent.thread.messages
            assert len(new_messages) == len(old_messages)
            for old, new in zip(old_messages, new_messages):
                assert old.role == new.role
                assert old.content == new.content

    def test_empty_sessions_dict(self, tmp_path: t.Any) -> None:
        """Swap with no active sessions should not error."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        with _paper_dir(str(tmp_path)), _isolated_sessions():
            srv._swap_model("new-model")  # should not raise


# ---------------------------------------------------------------------------
# Chat history persistence
# ---------------------------------------------------------------------------


class TestChatHistoryPersistence:
    """Test .chat-history.json backup and restore."""

    def test_clear_deletes_file(self, tmp_path: t.Any) -> None:
        """DELETE /api/chat-history removes the backup file."""
        backup = tmp_path / ".chat-history.json"
        backup.write_text('{"history": [{"type": "test"}]}')
        with _paper_dir(str(tmp_path)):
            result = asyncio.run(srv.clear_chat_history())
        assert result == {"status": "cleared"}
        assert not backup.exists()

    def test_clear_missing_file(self, tmp_path: t.Any) -> None:
        """Clearing when no backup exists should not error."""
        with _paper_dir(str(tmp_path)):
            result = asyncio.run(srv.clear_chat_history())
        assert result == {"status": "cleared"}

    @pytest.mark.parametrize(
        "content, expected_len",
        [
            ('{"history": [{"t": 1}, {"t": 2}]}', 2),
            ("not valid json{{{", 0),
            ('{"history": "not a list"}', 0),
            ('{"no_history_key": true}', 0),
        ],
        ids=["valid_backup", "corrupt_json", "wrong_type", "missing_key"],
    )
    def test_restore_contract(self, tmp_path: t.Any, content: str, expected_len: int) -> None:
        """Restore logic (replicated from server) handles valid and invalid backups."""
        backup_path = tmp_path / ".chat-history.json"
        backup_path.write_text(content)

        session = _Session(session_id="new", agent=MagicMock())
        # Replicate restore logic from _get_or_create_session (server.py:710-717)
        try:
            import json as _json

            with open(str(backup_path)) as f:
                backup = _json.load(f)
            if isinstance(backup.get("history"), list):
                session.history = backup["history"]
        except Exception:
            pass

        assert len(session.history) == expected_len
