"""Tests for ui/backend — tools, agent factory, event formatting, sessions."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import typing as t
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add ui/ to path so we can import backend.*
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
sys.path.insert(0, UI_DIR)

from backend.agent import _load_paper_context, create_agent  # noqa: E402
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
            "web_fetch",
            "web_search",
            "command",
            "read_file",
            "write_file",
            "finish_task",
            "give_up_on_task",
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


class TestFormatEvent:
    """Test _format_event with minimal mock events."""

    @staticmethod
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

    def test_agent_start(self) -> None:
        from dreadnode.agent.events import AgentStart

        result = _format_event(AgentStart(**self._base_fields()))
        assert result == {"type": "agent_start", "agent": "test-agent"}

    def test_step_start(self) -> None:
        from dreadnode.agent.events import StepStart

        result = _format_event(StepStart(**self._base_fields(), step=3))
        assert result == {"type": "step_start", "step": 3}

    def test_generation_end(self) -> None:
        from dreadnode.agent.events import GenerationEnd

        import rigging as rg

        msg = rg.Message("assistant", "Here is my response.")
        usage = rg.generator.Usage(input_tokens=100, output_tokens=50, total_tokens=150)
        result = _format_event(
            GenerationEnd(**self._base_fields(), message=msg, usage=usage)
        )
        assert result is not None
        assert result["type"] == "generation"
        assert result["content"] == "Here is my response."
        assert result["role"] == "assistant"
        assert result["usage"]["total_tokens"] == 150

    def test_generation_end_no_usage(self) -> None:
        from dreadnode.agent.events import GenerationEnd

        import rigging as rg

        msg = rg.Message("assistant", "Response without usage.")
        result = _format_event(
            GenerationEnd(**self._base_fields(), message=msg, usage=None)
        )
        assert result is not None
        assert result["usage"] is None
        assert result["content"] == "Response without usage."

    def test_tool_start(self) -> None:
        from dreadnode.agent.events import ToolStart

        tc = MagicMock()
        tc.name = "build_paper"
        tc.function.arguments = '{"timeout": 120}'
        result = _format_event(ToolStart(**self._base_fields(), tool_call=tc))
        assert result == {
            "type": "tool_start",
            "tool": "build_paper",
            "args": '{"timeout": 120}',
        }

    def test_tool_end_truncates(self) -> None:
        from dreadnode.agent.events import ToolEnd

        import rigging as rg

        tc = MagicMock()
        tc.name = "web_fetch"
        long_content = "x" * 3000
        msg = rg.Message("tool", long_content)
        result = _format_event(
            ToolEnd(**self._base_fields(), tool_call=tc, message=msg, stop=False)
        )
        assert result is not None
        assert len(result["result"]) == 2000
        assert result["stop"] is False

    def test_agent_error(self) -> None:
        from dreadnode.agent.events import AgentError

        result = _format_event(
            AgentError(**self._base_fields(), error=RuntimeError("boom"))
        )
        assert result is not None
        assert result["type"] == "error"
        assert "boom" in result["message"]

    def test_stalled(self) -> None:
        from dreadnode.agent.events import AgentStalled

        result = _format_event(AgentStalled(**self._base_fields()))
        assert result == {"type": "stalled"}

    def test_reacted_retry_with_feedback(self) -> None:
        from dreadnode.agent.events import Reacted
        from dreadnode.agent.reactions import RetryWithFeedback

        reaction = RetryWithFeedback(feedback="Try using a different tool.")
        result = _format_event(
            Reacted(**self._base_fields(), hook_name="my_hook", reaction=reaction)
        )
        assert result is not None
        assert result["type"] == "reacted"
        assert "RetryWithFeedback" in result["content"]
        assert "Try using a different tool." in result["content"]

    def test_reacted_finish(self) -> None:
        from dreadnode.agent.events import Reacted
        from dreadnode.agent.reactions import Finish

        reaction = Finish(reason="Task complete")
        result = _format_event(
            Reacted(**self._base_fields(), hook_name="done_hook", reaction=reaction)
        )
        assert result is not None
        assert "Finish" in result["content"]
        assert "Task complete" in result["content"]

    def test_agent_end(self) -> None:
        from dreadnode.agent.events import AgentEnd
        from dreadnode.agent.result import AgentResult

        import rigging as rg

        mock_result = MagicMock(spec=AgentResult)
        mock_result.failed = False
        mock_result.steps = 5
        mock_result.usage = rg.generator.Usage(
            input_tokens=500, output_tokens=200, total_tokens=700
        )
        result = _format_event(
            AgentEnd(**self._base_fields(), stop_reason="finished", result=mock_result)
        )
        assert result is not None
        assert result["type"] == "agent_end"
        assert result["stop_reason"] == "finished"
        assert result["failed"] is False
        assert result["steps"] == 5
        assert result["usage"]["total_tokens"] == 700

    def test_unknown_event_returns_none(self) -> None:
        from dreadnode.agent.events import AgentEvent

        result = _format_event(AgentEvent(**self._base_fields()))
        assert result is None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    def setup_method(self) -> None:
        """Clear global session store before each test."""
        _sessions.clear()

    def test_prune_removes_expired(self) -> None:
        _sessions["old"] = _Session(
            session_id="old",
            agent=MagicMock(),
            last_active=time.time() - 7200,
        )
        _sessions["new"] = _Session(
            session_id="new",
            agent=MagicMock(),
            last_active=time.time(),
        )
        _prune_sessions()
        assert "old" not in _sessions
        assert "new" in _sessions

    def test_prune_keeps_active(self) -> None:
        _sessions["active"] = _Session(
            session_id="active",
            agent=MagicMock(),
            last_active=time.time() - 60,
        )
        _prune_sessions()
        assert "active" in _sessions

    def test_prune_empty(self) -> None:
        _prune_sessions()
        assert len(_sessions) == 0
