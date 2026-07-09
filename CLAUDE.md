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
| `python3 scripts/reviews.py` | List and summarize peer reviews |

See `AGENT.md` for detailed instructions on each workflow.

## Capabilities

Extended agent capabilities beyond core document authoring. See `capabilities/README.md` for full details.

| Command | Purpose |
|---------|---------|
| `/lit-review "topic"` | Full literature review: search → analyze → synthesize → report |
| `/verify-claims section/01_introduction.tex` | Extract claims from LaTeX, verify against evidence |
| `/search-sources "query"` | Quick source discovery (no deep analysis) |
| `/analyze-source <URL or path> "context"` | Deep-read a single source into a structured card |
| `/peer-review` | Interactive review session — record notes into structured review record |

Reports are written to `capabilities/reports/`. Peer review records are saved to `reviews/` and tracked in git.

## Web UI

Local web interface with a terminal-style chat (left pane) and live PDF viewer (right pane). Uses dreadnode SDK's `TaskAgent` with rigging for LLM integration.

### Launching

```bash
# Quick start (builds frontend automatically if needed)
bash scripts/launch-ui.sh --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY

# For a paper in another directory
bash scripts/launch-ui.sh --paper /path/to/paper --model gpt-4o --api-key-env OPENAI_API_KEY

# Dev mode (frontend hot-reload on port 3000)
ui/backend/.venv/bin/python3 scripts/ui.py --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY --dev
# Then in another terminal: npm run dev --prefix ui/frontend
```

### Structure

```
ui/
├── backend/
│   ├── agent.py           # Agent factory, instructions, paper.yaml context
│   ├── server.py          # FastAPI + WebSocket + PDF watcher + sessions
│   ├── tools/
│   │   ├── subprocess.py  # Async subprocess runner with cancellation
│   │   ├── web.py         # web_fetch + web_search (Tavily)
│   │   └── latex.py       # 10 LaTeX script tools (closure over paper_dir)
│   └── requirements.txt
├── frontend/              # React + Vite + TypeScript
│   └── src/
│       ├── App.tsx                    # Split-pane layout with resizer
│       ├── components/TerminalChat.tsx # Terminal chat with session recovery
│       ├── components/PdfViewer.tsx    # pdf.js viewer with auto-reload
│       └── hooks/useWebSocket.ts      # WebSocket hook with reconnect
└── .gitignore
```

### Running tests

```bash
ui/backend/.venv/bin/python3 -m pytest tests/test_ui.py -v
```
