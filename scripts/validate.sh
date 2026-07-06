#!/usr/bin/env bash
# Validate LaTeX source files for common issues.
# Usage: ./scripts/validate.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ERRORS=0

echo "=== Validating LaTeX sources ==="
echo ""

# Check that all section files referenced in main.tex exist
echo "--- Checking section file references ---"
while IFS= read -r line; do
  # Extract filename from \input{section/...}
  file=$(echo "$line" | sed -n 's/.*\\input{section\/\([^}]*\)}.*/\1/p')
  if [[ -n "$file" ]]; then
    if [[ ! -f "$PROJECT_ROOT/section/${file}.tex" ]]; then
      echo "MISSING: section/${file}.tex (referenced in main.tex)"
      ERRORS=$((ERRORS + 1))
    else
      echo "  OK: section/${file}.tex"
    fi
  fi
done < "$PROJECT_ROOT/main.tex"
echo ""

# Check for unresolved markers (\tbd, \note, \todo)
echo "--- Checking for draft markers ---"
MARKER_COUNT=$(grep -rE '\\(tbd|note|todo)\{' "$PROJECT_ROOT/section/" 2>/dev/null | wc -l | tr -d ' ')
if [[ "$MARKER_COUNT" -gt 0 ]]; then
  echo "  Found $MARKER_COUNT draft marker(s):"
  grep -rnE '\\(tbd|note|todo)\{' "$PROJECT_ROOT/section/" 2>/dev/null | sed 's/^/    /'
else
  echo "  No draft markers found."
fi
echo ""

# Check sync status (paper.yaml sections vs main.tex \input lines)
echo "--- Checking sync status ---"
YAML_SECTIONS=$(python3 -c "import yaml; m=yaml.safe_load(open('$PROJECT_ROOT/paper.yaml')); print('\n'.join(s['slug'] for s in m.get('sections',[])))" 2>/dev/null)
TEX_SECTIONS=$(sed -n 's/.*\\input{section\/\([^}]*\)}/\1/p' "$PROJECT_ROOT/main.tex" 2>/dev/null)
if [[ "$YAML_SECTIONS" != "$TEX_SECTIONS" ]]; then
  echo "  WARNING: paper.yaml and main.tex sections are out of sync"
  echo "  Run: python3 scripts/sync.py"
  ERRORS=$((ERRORS + 1))
else
  echo "  OK: paper.yaml and main.tex are in sync"
fi
echo ""

# Check for common LaTeX issues
echo "--- Checking for common issues ---"
# Unmatched braces (basic check)
for texfile in "$PROJECT_ROOT"/section/*.tex "$PROJECT_ROOT"/main.tex; do
  if [[ -f "$texfile" ]]; then
    OPEN=$(tr -cd '{' < "$texfile" | wc -c | tr -d ' ')
    CLOSE=$(tr -cd '}' < "$texfile" | wc -c | tr -d ' ')
    if [[ "$OPEN" -ne "$CLOSE" ]]; then
      echo "  WARNING: Mismatched braces in $(basename "$texfile") (open=$OPEN, close=$CLOSE)"
      ERRORS=$((ERRORS + 1))
    fi
  fi
done

# Run chktex if available
if command -v chktex &>/dev/null; then
  echo ""
  echo "--- Running chktex ---"
  chktex -q "$PROJECT_ROOT/main.tex" 2>/dev/null || true
fi

echo ""
if [[ $ERRORS -gt 0 ]]; then
  echo "=== Validation found $ERRORS error(s) ==="
  exit 1
else
  echo "=== Validation passed ==="
  exit 0
fi
