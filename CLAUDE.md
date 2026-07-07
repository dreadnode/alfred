# Agentic LaTeX

## Workflow

When starting a new paper:

1. Set `template` in `paper.yaml` (or run `python3 scripts/init_template.py <name>`)
2. Fill in `title`, `authors`, `abstract_summary` in `paper.yaml`
3. Define your sections in `paper.yaml` under `sections:`
4. Run `python3 scripts/sync.py` to update main.tex and create section files
5. Write content in each `section/*.tex` file — one section at a time
6. Add citations with `python3 scripts/cite.py search "query"` then `python3 scripts/cite.py add <ID>`
7. Build with `bash scripts/build.sh` — fix any errors from `build/main.log`
8. Check progress with `python3 scripts/stats.py`
9. Update section status in `paper.yaml` as you go (draft → in_progress → complete)
10. Validate with `bash scripts/validate.sh` before finalizing

## Rules

- **paper.yaml is the source of truth** — edit it first, then sync
- Edit content in `section/*.tex` files, never in `main.tex` body
- Never hand-edit `% BEGIN SYNC` / `% END SYNC` regions — managed by sync
- One sentence per line in .tex source for clean diffs

## Scripts

| Command | Purpose |
|---------|---------|
| `python3 scripts/sync.py` | Sync paper.yaml → main.tex |
| `bash scripts/build.sh` | Build PDF → `build/main.pdf` |
| `bash scripts/validate.sh` | Check refs, markers, braces, sync status |
| `python3 scripts/cite.py search "query"` | Search Semantic Scholar |
| `python3 scripts/cite.py add <ID>` | Add citation to bibliography.bib |
| `python3 scripts/stats.py` | Word count, pages, figures, tables |
| `python3 scripts/diff.py [rev]` | Track-changes PDF → `build/diff.pdf` |
| `python3 scripts/init_template.py <name>` | Switch conference template |

See `AGENT.md` for detailed instructions on each workflow.

## Literature Review & Claim Verification

Multi-agent workflow for finding and synthesizing prior work, or verifying claims against evidence. See `lit-review-and-claim-verifier/README.md` for full details.

| Command | Purpose |
|---------|---------|
| `/lit-review "topic"` | Full literature review: search → analyze → synthesize → report |
| `/verify-claims section/01_introduction.tex` | Extract claims from LaTeX, verify against evidence |
| `/search-sources "query"` | Quick source discovery (no deep analysis) |
| `/analyze-source <URL or path> "context"` | Deep-read a single source into a structured card |

Reports are written to `lit-review-and-claim-verifier/reports/`.
