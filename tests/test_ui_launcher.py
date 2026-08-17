"""Tests for the top-level ALFRED UI launcher."""

from __future__ import annotations

import importlib.util
import sys
import typing as t
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _load_launcher() -> t.Any:
    """Load scripts/ui.py without colliding with the ui package directory."""
    path = Path(__file__).parents[1] / "scripts" / "ui.py"
    spec = importlib.util.spec_from_file_location("alfred_ui_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = _load_launcher()


def test_launcher_configures_websocket_limit_for_base64_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = MagicMock()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ui.py", "--model", "test-model", "--dev", "--no-browser"],
    )
    monkeypatch.setattr(launcher.uvicorn, "run", run)

    launcher.main()

    assert run.call_args.kwargs["ws_max_size"] == 32 * 1024 * 1024
    encoded_image_limit = 4 * (((16 * 1024 * 1024) + 2) // 3)
    assert encoded_image_limit < run.call_args.kwargs["ws_max_size"]


def test_api_key_is_read_from_named_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALFRED_TEST_API_KEY", "dummy-secret")

    assert launcher._resolve_api_key("ALFRED_TEST_API_KEY", "gpt-4o") == "gpt-4o"


def test_raw_api_key_argument_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_key = "sk-dummy-not-a-secret"
    with pytest.raises(SystemExit) as exc_info:
        launcher._resolve_api_key(raw_key, "gpt-4o")

    stderr = capsys.readouterr().err
    assert exc_info.value.code == 1
    assert "environment variable name" in stderr
    assert raw_key not in stderr


def test_legacy_api_key_option_is_removed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_key = "sk-dummy-not-a-secret"
    monkeypatch.setattr(
        sys,
        "argv",
        ["ui.py", "--model", "gpt-4o", "--api-key", raw_key],
    )

    with pytest.raises(SystemExit) as exc_info:
        launcher.main()

    stderr = capsys.readouterr().err
    assert exc_info.value.code == 2
    assert "invalid command-line arguments" in stderr
    assert raw_key not in stderr


def test_openrouter_environment_variable_routes_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-secret")

    assert (
        launcher._resolve_api_key("OPENROUTER_API_KEY", "openai/gpt-4o")
        == "openrouter/openai/gpt-4o"
    )
