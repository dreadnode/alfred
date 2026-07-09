"""Tests for ui/backend — tools, agent factory, event formatting, sessions."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import typing as t
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add ui/ to path so we can import backend.*
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
sys.path.insert(0, UI_DIR)

from backend.agent import _load_paper_context, create_agent
from backend.server import _Session, _format_event, _prune_sessions, _sessions
from backend.tools.subprocess import run_script
from backend.tools.web import _strip_html


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_basic_tags(self) -> None:
        assert _strip_html("<p>hello</p>") == "hello"

    def test_nested_tags(self) -> None:
        assert _strip_html("<div><p>hello <b>world</b></p></div>") == "hello world"

    def test_script_removal(self) -> None:
        html = '<p>before</p><script type="text/javascript">alert("xss")</script><p>after</p>'
        result = _strip_html(html)
        assert "alert" not in result
        assert "before" in result
        assert "after" in result

    def test_style_removal(self) -> None:
        html = "<style>.foo { color: red; }</style><p>content</p>"
        result = _strip_html(html)
        assert "color" not in result
        assert "content" in result

    def test_comment_removal(self) -> None:
        html = "<p>before</p><!-- secret comment --><p>after</p>"
        result = _strip_html(html)
        assert "secret" not in result
        assert "before" in result

    def test_entity_decoding(self) -> None:
        assert _strip_html("<p>AT&amp;T &lt;3&gt;</p>") == "AT&T <3>"

    def test_numeric_entity(self) -> None:
        assert _strip_html("<p>&#8217;</p>") == "\u2019"

    def test_whitespace_collapse(self) -> None:
        html = "<p>  lots   of    space  </p>"
        assert _strip_html(html) == "lots of space"

    def test_empty_input(self) -> None:
        assert _strip_html("") == ""

    def test_multiline_script(self) -> None:
        html = "<script>\nvar x = 1;\nvar y = 2;\n</script><p>ok</p>"
        assert _strip_html(html) == "ok"


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
        # Should not crash — returns empty or partial
        result = _load_paper_context(str(tmp_path))
        assert isinstance(result, str)

    def test_minimal_yaml(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text("title: Untitled\n")
        ctx = _load_paper_context(str(tmp_path))
        assert "Untitled" in ctx

    def test_non_dict_macros(self, tmp_path: t.Any) -> None:
        """macros as a list should not crash."""
        (tmp_path / "paper.yaml").write_text(
            'title: "Test"\n' "macros:\n" "  - foo\n" "  - bar\n"
        )
        ctx = _load_paper_context(str(tmp_path))
        assert "Macros defined" not in ctx  # skipped, not a dict

    def test_non_list_styles(self, tmp_path: t.Any) -> None:
        """styles as a string should not crash."""
        (tmp_path / "paper.yaml").write_text(
            'title: "Test"\n' 'styles: "messageboxes"\n'
        )
        ctx = _load_paper_context(str(tmp_path))
        assert "Style packages" not in ctx  # skipped, not a list


# ---------------------------------------------------------------------------
# run_script
# ---------------------------------------------------------------------------


class TestRunScript:
    def test_success(self) -> None:
        result = asyncio.run(run_script("echo", "hello", cwd="/tmp"))
        assert result.strip() == "hello"

    def test_failure_raises(self) -> None:
        with pytest.raises(RuntimeError, match="failed"):
            asyncio.run(run_script("false", cwd="/tmp"))

    def test_timeout_raises(self) -> None:
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            asyncio.run(run_script("sleep", "10", cwd="/tmp", timeout=1))

    def test_stderr_merged(self) -> None:
        """stderr is merged into stdout."""
        result = asyncio.run(
            run_script("bash", "-c", "echo out && echo err >&2", cwd="/tmp")
        )
        assert "out" in result
        assert "err" in result

    def test_nonexistent_command(self) -> None:
        with pytest.raises((FileNotFoundError, RuntimeError)):
            asyncio.run(
                run_script("nonexistent_command_xyz_123", cwd="/tmp")
            )


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------


class TestCreateAgent:
    def test_creates_agent(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        agent = create_agent("test-model", str(tmp_path))
        assert agent.name == "latex-agent"
        assert agent.max_steps == 50

    def test_tool_count(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        agent = create_agent("test-model", str(tmp_path))
        names = [t.name for t in agent.all_tools]
        # 12 fs/command tools + 2 web tools + 10 latex tools + 3 task agent built-ins = 27
        assert len(names) == 27

    def test_latex_tools_present(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        agent = create_agent("test-model", str(tmp_path))
        names = {t.name for t in agent.all_tools}
        for expected in [
            "build_paper", "sync_paper", "validate_paper",
            "search_citations", "add_citation", "paper_stats",
            "generate_diff", "switch_template", "list_templates", "list_reviews",
        ]:
            assert expected in names, f"Missing tool: {expected}"

    def test_web_tools_present(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        agent = create_agent("test-model", str(tmp_path))
        names = {t.name for t in agent.all_tools}
        assert "web_fetch" in names
        assert "web_search" in names

    def test_latex_tools_no_paper_dir_param(self, tmp_path: t.Any) -> None:
        """Latex tools should not expose paper_dir to the LLM."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        agent = create_agent("test-model", str(tmp_path))
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

    def test_invalid_api_key_env(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        with pytest.raises(ValueError, match="NONEXISTENT_VAR"):
            create_agent("test-model", str(tmp_path), api_key_env="NONEXISTENT_VAR")

    def test_hooks_registered(self, tmp_path: t.Any) -> None:
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        agent = create_agent("test-model", str(tmp_path))
        hook_names = [
            h.__name__ if hasattr(h, "__name__") else type(h).__name__
            for h in agent.hooks
        ]
        assert "summarize_when_long" in hook_names
        assert "retry_with_feedback" in hook_names

    def test_web_search_no_key_graceful(self, tmp_path: t.Any) -> None:
        """web_search should return fallback message when no API key is configured."""
        (tmp_path / "paper.yaml").write_text('title: "Test"\n')
        agent = create_agent("test-model", str(tmp_path))
        search_tool = next(t for t in agent.all_tools if t.name == "web_search")
        tc = MagicMock()
        tc.id = "test"
        tc.name = "web_search"
        tc.function.arguments = json.dumps({"query": "test"})
        msg, stop = asyncio.run(search_tool.handle_tool_call(tc))
        assert "not configured" in msg.content.lower() or "search_citations" in msg.content


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
        thread = MagicMock()
        return {
            "session_id": MagicMock(),
            "agent": agent,
            "thread": thread,
            "messages": [],
            "events": [],
        }

    def test_agent_start(self) -> None:
        from dreadnode.agent.events import AgentStart

        event = AgentStart(**self._base_fields())
        result = _format_event(event)
        assert result == {"type": "agent_start", "agent": "test-agent"}

    def test_step_start(self) -> None:
        from dreadnode.agent.events import StepStart

        event = StepStart(**self._base_fields(), step=3)
        result = _format_event(event)
        assert result == {"type": "step_start", "step": 3}

    def test_agent_error(self) -> None:
        from dreadnode.agent.events import AgentError

        event = AgentError(**self._base_fields(), error=RuntimeError("boom"))
        result = _format_event(event)
        assert result is not None
        assert result["type"] == "error"
        assert "boom" in result["message"]

    def test_stalled(self) -> None:
        from dreadnode.agent.events import AgentStalled

        event = AgentStalled(**self._base_fields())
        result = _format_event(event)
        assert result == {"type": "stalled"}

    def test_unknown_event_returns_none(self) -> None:
        from dreadnode.agent.events import AgentEvent

        event = AgentEvent(**self._base_fields())
        result = _format_event(event)
        assert result is None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    def test_prune_removes_expired(self) -> None:
        import time

        _sessions.clear()
        _sessions["old"] = _Session(
            session_id="old",
            agent=MagicMock(),
            last_active=time.time() - 7200,  # 2 hours ago
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
        import time

        _sessions.clear()
        _sessions["active"] = _Session(
            session_id="active",
            agent=MagicMock(),
            last_active=time.time() - 60,  # 1 minute ago
        )
        _prune_sessions()
        assert "active" in _sessions

    def test_prune_empty_is_noop(self) -> None:
        _sessions.clear()
        _prune_sessions()  # should not raise
        assert len(_sessions) == 0
