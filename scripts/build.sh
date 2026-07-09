#!/usr/bin/env bash
# Build the LaTeX document using latexmk.
# Usage: ./scripts/build.sh [--clean]
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "${1:-}" == "--clean" ]]; then
  echo "=== Cleaning build artifacts ==="
  rm -rf "$PROJECT_ROOT/build"
  echo "Done."
  exit 0
fi

echo "=== Building document ==="
cd "$PROJECT_ROOT"
mkdir -p build
latexmk -pdf -outdir=build main.tex

EXIT_CODE=$?
if [[ $EXIT_CODE -eq 0 ]]; then
  echo ""
  echo "=== Build successful ==="
  echo "Output: build/main.pdf"
else
  echo ""
  echo "=== Build FAILED (exit code: $EXIT_CODE) ==="
  echo "Check build/main.log for details."
fi

exit $EXIT_CODE
