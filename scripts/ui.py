#!/usr/bin/env python3
"""Launch the ALFRED web UI.

Usage::

    ./alfred --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY
    ./alfred --paper /path/to/paper --model gpt-4o --api-key-env OPENAI_API_KEY
"""

import argparse
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn
from credentials import read_secret_from_env

MAX_WEBSOCKET_MESSAGE_BYTES = 32 * 1024 * 1024


def _resolve_api_key(value: str | None, model: str) -> str:
    """Validate an API-key environment variable and return the routed model.

    Raw keys are intentionally rejected because command-line arguments can be
    exposed through process listings and shell history.

    If the env var is ``OPENROUTER_API_KEY``, the model is prefixed with
    ``openrouter/`` for litellm routing.

    Args:
        value: The ``--api-key-env`` variable name, or ``None``.
        model: The model identifier (used to infer the provider).

    Returns:
        The model identifier, possibly prefixed for the provider.
    """
    if not value:
        return model

    try:
        read_secret_from_env(value)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if value == "OPENROUTER_API_KEY" and not model.startswith("openrouter/"):
        return f"openrouter/{model}"
    return model


# ANSI color codes for styled terminal output (disabled when piped or NO_COLOR is set)
if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
    _TEAL = "\033[38;2;0;128;128m"
    _DIM = "\033[2m"
    _BOLD = "\033[1m"
    _RESET = "\033[0m"
else:
    _TEAL = _DIM = _BOLD = _RESET = ""


def _print_help() -> None:
    """Print styled help and exit."""
    w = 68

    options = [
        ("--model <id>", "LLM model identifier (required)"),
        ("--api-key-env <name>", "Environment variable containing the API key"),
        ("--paper <path>", "Open with this paper (creates a session)"),
        ("--port <n>", "Server port (default: 8420)"),
        ("--no-browser", "Don't open browser on launch"),
        ("--dev", "Dev mode (frontend on port 3000)"),
        ("-h, --help", "Show this help message"),
    ]

    lines = [
        "",
        f"  {_TEAL}{_BOLD}ALFRED{_RESET} {_DIM}— Agentic LaTeX for Research, Editing, and Drafting{_RESET}",
        f"  {_TEAL}{'─' * w}{_RESET}",
        "",
        f"  {_BOLD}Usage:{_RESET}",
        f"    {_DIM}${_RESET} ./alfred --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY",
        f"    {_DIM}${_RESET} ./alfred --paper /path/to/paper --model gpt-4o --api-key-env OPENAI_API_KEY",
        "",
        f"  {_BOLD}Options:{_RESET}",
    ]

    for flag, desc in options:
        lines.append(f"    {_TEAL}{flag:<22}{_RESET} {desc}")

    lines += [
        "",
        f"  {_BOLD}Notes:{_RESET}",
        f"    {_DIM}•{_RESET} Multi-session: each paper gets its own tab",
        f"    {_DIM}•{_RESET} Use --paper to pre-create a session for an existing paper",
        f"    {_DIM}•{_RESET} New papers are created in ./papers/ by default",
        f"    {_DIM}•{_RESET} API keys are read from environment variables, never command-line values",
        f"    {_DIM}•{_RESET} Works with any model supported by rigging/litellm",
        "",
        f"  {_TEAL}{'─' * w}{_RESET}",
        "",
    ]
    print("\n".join(lines))
    sys.exit(0)


def main() -> None:
    """Parse CLI arguments, configure the backend, and start the server."""
    if any(
        argument == "--api-key" or argument.startswith("--api-key=")
        for argument in sys.argv[1:]
    ):
        print("Error: invalid command-line arguments", file=sys.stderr)
        sys.exit(2)

    if "--help" in sys.argv or "-h" in sys.argv:
        _print_help()

    parser = argparse.ArgumentParser(
        description="Launch the ALFRED web UI",
        add_help=False,
    )
    parser.add_argument(
        "--paper",
        default=None,
        help="Paper directory (creates a session for this paper)",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="LLM model identifier",
    )
    parser.add_argument(
        "--api-key-env",
        dest="api_key_env",
        default=None,
        help="Environment variable containing the API key",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8420,
        help="Server port (default: 8420)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser on launch",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Dev mode (frontend on port 3000)",
    )

    args = parser.parse_args()

    # Determine papers root (./papers/ relative to cwd)
    launch_dir = os.getcwd()
    papers_root = os.path.join(launch_dir, "papers")

    # Handle --paper: validate it exists
    paper_dir: str | None = None
    if args.paper:
        paper_dir = os.path.abspath(args.paper)
        if not os.path.isdir(paper_dir):
            print(f"Error: Paper directory not found: {paper_dir}", file=sys.stderr)
            sys.exit(1)
        if not os.path.isfile(os.path.join(paper_dir, "paper.yaml")):
            print(f"Error: No paper.yaml found in: {paper_dir}", file=sys.stderr)
            sys.exit(1)

    model: str = _resolve_api_key(args.api_key_env, args.model)

    ui_root: Path = Path(__file__).resolve().parent.parent / "ui"
    frontend_dist: Path = ui_root / "frontend" / "dist"

    if not args.dev and not frontend_dist.is_dir():
        print("Frontend not built. Building now...")
        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(ui_root / "frontend"),
            check=True,
        )

    # Deferred import — backend package is only on sys.path after the insert.
    sys.path.insert(0, str(ui_root))
    from backend.server import app, configure, mount_frontend

    configure(
        model=model,
        papers_root=papers_root,
        paper_dir=paper_dir,
        server_port=args.port,
        dev=args.dev,
    )

    if not args.dev and frontend_dist.is_dir():
        mount_frontend(str(frontend_dist))

    url: str = "http://localhost:3000" if args.dev else f"http://localhost:{args.port}"

    # Import version for banner
    from backend import __version__

    lines = []
    lines.append(f"  {_DIM}papers{_RESET}     {papers_root}")
    if paper_dir:
        lines.append(f"  {_DIM}paper{_RESET}      {paper_dir}")
    lines.append(f"  {_DIM}model{_RESET}      {model}")
    lines.append(f"  {_DIM}server{_RESET}     http://localhost:{args.port}")
    if args.dev:
        lines.append(f"  {_DIM}frontend{_RESET}   {url}")

    banner_width = 52
    print()
    print(f"  {_TEAL}{_BOLD}ALFRED{_RESET} {_DIM}v{__version__}{_RESET}")
    print(f"  {_TEAL}{'─' * banner_width}{_RESET}")
    for line in lines:
        print(line)
    print(f"  {_TEAL}{'─' * banner_width}{_RESET}")
    print()

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="info",
        ws_max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
    )


if __name__ == "__main__":
    main()
