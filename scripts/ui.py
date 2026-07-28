#!/usr/bin/env python3
"""Launch the ALFRED web UI.

Usage::

    ./al --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY
    ./al --model claude-sonnet-4-20250514 --api-key sk-ant-...
    ./al --paper /path/to/paper --model gpt-4o --api-key OPENAI_API_KEY
"""

import argparse
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn
from scaffold import scaffold_paper as _scaffold_paper


def _resolve_api_key(value: str | None, model: str) -> str:
    """Resolve ``--api-key`` value, set the right env var, and return the model.

    Accepts either an environment variable name (e.g. ``ANTHROPIC_API_KEY``)
    or a raw key (e.g. ``sk-ant-...``).  If a raw key is given, it is set
    into the environment variable that litellm expects for the provider.

    If the env var is ``OPENROUTER_API_KEY``, the model is prefixed with
    ``openrouter/`` for litellm routing.

    Args:
        value: The ``--api-key`` argument value, or ``None``.
        model: The model identifier (used to infer the provider).

    Returns:
        The model identifier, possibly prefixed for the provider.
    """
    if not value:
        return model

    # Check if it's an env var name (exists in environment)
    if os.environ.get(value):
        if value == "OPENROUTER_API_KEY" and not model.startswith("openrouter/"):
            return f"openrouter/{model}"
        return model

    # Check if it looks like an env var name (all caps, underscores) but isn't set
    if value.isupper() and "_" in value and not value.startswith(("sk-", "key-")):
        print(f"Error: Environment variable '{value}' is not set", file=sys.stderr)
        sys.exit(1)

    # It's a raw key — figure out which env var to set
    model_lower = model.lower()
    if "claude" in model_lower or "anthropic" in model_lower:
        env_var = "ANTHROPIC_API_KEY"
    elif (
        "gpt" in model_lower
        or "o1" in model_lower
        or "o3" in model_lower
        or "openai" in model_lower
    ):
        env_var = "OPENAI_API_KEY"
    elif "gemini" in model_lower or "google" in model_lower:
        env_var = "GOOGLE_API_KEY"
    elif "mistral" in model_lower:
        env_var = "MISTRAL_API_KEY"
    else:
        env_var = "OPENAI_API_KEY"

    os.environ[env_var] = value
    return model


def main() -> None:
    """Parse CLI arguments, configure the backend, and start the server."""
    parser = argparse.ArgumentParser(description="Launch the ALFRED web UI")
    parser.add_argument(
        "--paper",
        default=os.getcwd(),
        help="Path to the paper directory (default: current directory)",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="LLM model identifier (e.g. claude-sonnet-4-20250514, gpt-4o)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key or env var name (e.g. ANTHROPIC_API_KEY or sk-ant-...)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8420,
        help="Port for the backend server (default: 8420)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in dev mode (frontend dev server on port 3000)",
    )

    args = parser.parse_args()

    paper_dir: str = os.path.abspath(args.paper)
    if not os.path.isdir(paper_dir):
        print(f"Error: Paper directory not found: {paper_dir}", file=sys.stderr)
        sys.exit(1)

    workspace_root: str | None = None
    if os.path.isfile(os.path.join(paper_dir, "paper.yaml")):
        # Single-paper mode — backwards compatible.
        pass
    else:
        # Workspace mode — paper_dir is the workspace root.
        workspace_root = paper_dir
        # Find first existing paper subdir, or scaffold one.
        subdirs = sorted(
            d
            for d in os.listdir(paper_dir)
            if os.path.isdir(os.path.join(paper_dir, d))
            and os.path.isfile(os.path.join(paper_dir, d, "paper.yaml"))
        )
        if subdirs:
            paper_dir = os.path.join(workspace_root, subdirs[0])
        else:
            paper_dir = os.path.join(workspace_root, "untitled-paper")
            _scaffold_paper(paper_dir)

    model: str = _resolve_api_key(args.api_key, args.model)

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
        paper_dir=paper_dir,
        model=model,
        workspace_root=workspace_root,
    )

    if not args.dev and frontend_dist.is_dir():
        mount_frontend(str(frontend_dist))

    url: str = "http://localhost:3000" if args.dev else f"http://localhost:{args.port}"

    print("\n  ALFRED")
    if workspace_root:
        print(f"  Workspace: {workspace_root}")
    print(f"  Paper:  {paper_dir}")
    print(f"  Model:  {model}")
    print(f"  Server: http://localhost:{args.port}")
    if args.dev:
        print(f"  Frontend dev: {url}")
    print()

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
