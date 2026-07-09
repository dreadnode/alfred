#!/usr/bin/env python3
"""Launch the Agentic LaTeX web UI.

Usage (run from repo root with the backend venv)::

    ui/backend/.venv/bin/python3 scripts/ui.py \\
        --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY

    ui/backend/.venv/bin/python3 scripts/ui.py \\
        --paper /path/to/paper --model gpt-4o --api-key-env OPENAI_API_KEY

Or use the convenience script::

    bash scripts/launch-ui.sh --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY
"""

import argparse
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn


def main() -> None:
    """Parse CLI arguments, configure the backend, and start the server."""
    parser = argparse.ArgumentParser(description="Launch the Agentic LaTeX web UI")
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
        "--api-key-env",
        default=None,
        help="Environment variable name containing the API key (e.g. ANTHROPIC_API_KEY)",
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

    if not os.path.isfile(os.path.join(paper_dir, "paper.yaml")):
        print(f"Warning: No paper.yaml found in {paper_dir}", file=sys.stderr)

    if args.api_key_env and not os.environ.get(args.api_key_env):
        print(f"Error: Environment variable '{args.api_key_env}' is not set", file=sys.stderr)
        sys.exit(1)

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
        model=args.model,
        api_key_env=args.api_key_env,
    )

    if not args.dev and frontend_dist.is_dir():
        mount_frontend(str(frontend_dist))

    url: str = "http://localhost:3000" if args.dev else f"http://localhost:{args.port}"

    print("\n  Agentic LaTeX UI")
    print(f"  Paper:  {paper_dir}")
    print(f"  Model:  {args.model}")
    print(f"  Server: http://localhost:{args.port}")
    if args.dev:
        print(f"  Frontend dev: {url}")
    print()

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
