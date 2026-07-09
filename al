#!/usr/bin/env bash
# Launch the Agentic LaTeX web UI.
#
# Usage:
#   ./al --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY
#   ./al --paper /path/to/paper --model gpt-4o --api-key-env OPENAI_API_KEY

exec "$(dirname "$0")/scripts/launch-ui.sh" "$@"
