#!/usr/bin/env bash
# Convenience launcher for the ALFRED web UI.
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

# Build frontend if missing or source is newer than dist
FRONTEND_DIR="$REPO_ROOT/ui/frontend"
NEEDS_BUILD=false
if [ ! -d "$FRONTEND_DIR/dist" ]; then
    NEEDS_BUILD=true
else
    DIST_STAMP="$FRONTEND_DIR/dist/.build_stamp"
    if [ ! -f "$DIST_STAMP" ]; then
        NEEDS_BUILD=true
    elif [ -n "$(find "$FRONTEND_DIR/src" "$FRONTEND_DIR/package.json" "$FRONTEND_DIR/index.html" "$FRONTEND_DIR/vite.config.ts" "$FRONTEND_DIR/tsconfig.json" -newer "$DIST_STAMP" 2>/dev/null)" ]; then
        NEEDS_BUILD=true
    fi
fi
if [ "$NEEDS_BUILD" = true ]; then
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        echo "Installing frontend dependencies..."
        npm ci --prefix "$FRONTEND_DIR"
    fi
    echo "Building frontend..."
    npm run build --prefix "$FRONTEND_DIR"
    touch "$FRONTEND_DIR/dist/.build_stamp"
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/ui.py" "$@"
