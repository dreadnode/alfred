#!/usr/bin/env bash
# Convenience launcher for the Agentic LaTeX web UI.
# Automatically uses the backend venv Python.
#
# Usage:
#   bash scripts/launch-ui.sh --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY
#   bash scripts/launch-ui.sh --paper /path/to/paper --model gpt-4o --api-key-env OPENAI_API_KEY

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$REPO_ROOT/ui/backend/.venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Backend venv not found. Setting up..."
    uv venv "$REPO_ROOT/ui/backend/.venv"
    uv pip install --python "$VENV_PYTHON" -r "$REPO_ROOT/ui/backend/requirements.txt"
fi

# Build frontend if not already built
if [ ! -d "$REPO_ROOT/ui/frontend/dist" ]; then
    echo "Building frontend..."
    npm run build --prefix "$REPO_ROOT/ui/frontend"
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/ui.py" "$@"
