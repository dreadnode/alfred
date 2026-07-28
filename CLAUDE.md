# ALFRED

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

Slash commands available in the web UI and Claude Code. See `capabilities/README.md` for full details.

| Command | Purpose |
|---------|---------|
| `/analyze-source <URL> "context"` | Deep-read a single source into a structured card |
| `/detect-llm-writing [file]` | Analyze prose for LLM writing indicators |
| `/lit-review "topic"` | Full literature review: search → analyze → synthesize → report |
| `/peer-review` | Interactive review session — record notes into structured review record |
| `/process-peer-review [file]` | Process a peer review — address, accept, or refute each item |
| `/search-sources "query"` | Quick source discovery (no deep analysis) |
| `/verify-claims section/file.tex` | Extract claims from LaTeX, verify against evidence |

Reports are written to `capabilities/reports/`. Peer review records and responses are saved to `reviews/`.

## Web UI

Local web interface with a terminal-style chat (left pane) and live PDF viewer (right pane). Uses dreadnode SDK's `TaskAgent` with rigging for LLM integration.

### Launching

```bash
# Quick start — pass env var name or raw key
./alfred --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY
./alfred --model claude-sonnet-4-20250514 --api-key sk-ant-...

# Workspace mode — launch in an empty directory for multi-paper support
mkdir workspace && cd workspace
/path/to/alfred/alfred --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY

# Single-paper mode — point to an existing paper directory
./alfred --paper /path/to/paper --model gpt-4o --api-key OPENAI_API_KEY

# Dev mode (frontend hot-reload on port 3000)
./alfred --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY --dev
```

### Features

- **Slash command autocomplete** — type `/` to see available commands with descriptions
- **Settings popup** — click the model name to change model and API key at runtime
- **Paper title editing** — click the paper title above the PDF viewer to rename
- **Workspace mode** — paper switcher bar with dropdown and "+ NEW" button when launched without a paper.yaml
- **Session recovery** — WebSocket reconnects and replays chat history automatically

### Structure

```
ui/
├── backend/
│   ├── agent.py           # Agent factory, instructions, paper.yaml context
│   ├── capabilities.py    # Slash command registry, parser, prompt expansion
│   ├── server.py          # FastAPI + WebSocket + PDF watcher + sessions
│   ├── tools/
│   │   ├── subprocess.py  # Async subprocess runner with cancellation
│   │   ├── web.py         # web_fetch + web_search (DuckDuckGo)
│   │   └── latex.py       # 10 LaTeX script tools (closure over paper_dir)
│   └── requirements.txt
├── frontend/              # React + Vite + TypeScript
│   └── src/
│       ├── App.tsx                    # Split-pane layout, workspace bar, paper switcher
│       ├── components/TerminalChat.tsx # Terminal chat, command autocomplete, settings
│       ├── components/PdfViewer.tsx    # pdf.js viewer with auto-reload, title editing
│       └── hooks/useWebSocket.ts      # WebSocket hook with reconnect
└── .gitignore
```

### Running tests

```bash
task test          # Run all tests
task lint          # Ruff format check + lint
task fmt           # Auto-format Python
task build         # Build frontend
task check         # fmt + lint + test
```
