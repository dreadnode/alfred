"""Tests for slash-command capability expansion."""

from __future__ import annotations

import os
import sys

UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
sys.path.insert(0, UI_DIR)

from backend.capabilities import (  # noqa: E402
    CAPABILITIES,
    _REPO_ROOT,
    maybe_expand_command,
    parse_slash_command,
)


class TestParseSlashCommand:
    def test_parses_command_and_strips_quotes(self) -> None:
        assert parse_slash_command('/lit-review "my topic"') == (
            "lit-review",
            "my topic",
        )
        assert parse_slash_command("/search-sources no quotes") == (
            "search-sources",
            "no quotes",
        )
        assert parse_slash_command("/peer-review") == ("peer-review", "")

    def test_rejects_non_commands(self) -> None:
        assert parse_slash_command("hello world") is None
        assert parse_slash_command("use /lit-review for that") is None

    def test_extra_whitespace(self) -> None:
        assert parse_slash_command('/lit-review   "spaced out"') == (
            "lit-review",
            "spaced out",
        )
        assert parse_slash_command("  /peer-review  ") == ("peer-review", "")

    def test_empty_quoted_arg(self) -> None:
        assert parse_slash_command('/lit-review ""') == ("lit-review", "")


class TestMaybeExpandCommand:
    def test_unknown_command_returns_error(self) -> None:
        result = maybe_expand_command("/foo bar")
        assert "Unknown command: /foo" in result
        assert "/lit-review" in result

    def test_missing_required_args(self) -> None:
        result = maybe_expand_command("/lit-review")
        assert "requires" in result
        assert "topic" in result

    def test_optional_args_allowed_empty(self) -> None:
        result = maybe_expand_command("/peer-review")
        assert "=== CAPABILITY: peer-review ===" in result

    def test_expansion_assembles_full_prompt(self) -> None:
        result = maybe_expand_command('/search-sources "reward hacking"')
        assert "=== CAPABILITY: search-sources ===" in result
        assert "## Skill Instructions" in result
        assert "## Guidance:" in result
        assert "=== USER REQUEST ===" in result
        assert "/search-sources reward hacking" in result

    def test_all_registered_files_exist(self) -> None:
        expected = {
            "search-sources",
            "analyze-source",
            "lit-review",
            "verify-claims",
            "peer-review",
            "process-peer-review",
            "spellcheck",
            "detect-llm-writing",
        }
        assert set(CAPABILITIES.keys()) == expected
        for name, cap in CAPABILITIES.items():
            assert os.path.isfile(os.path.join(_REPO_ROOT, cap["skill"])), (
                f"Missing skill for /{name}"
            )
            for rel_path in cap["extra_files"]:
                assert os.path.isfile(os.path.join(_REPO_ROOT, rel_path)), (
                    f"Missing {rel_path} for /{name}"
                )
