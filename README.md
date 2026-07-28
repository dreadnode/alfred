# ALFRED

**A**gentic **L**atex **f**or **R**esearch, **E**diting, and **D**rafting.

Clone the repo, point an AI coding agent at it, give it a topic — it writes the paper.

![ALFRED web UI](docs/agentic-latex-ss-2.png)

## Features

### Built-in

The agent handles these automatically as part of the writing workflow — just tell it what you want.

- **Conference templates** — 6 formats (NeurIPS, IEEE, ACM, USENIX, ACL, plain article), switch by asking
- **YAML-driven sync** — paper structure defined in `paper.yaml`, agent syncs to `main.tex` automatically
- **PDF build** — compiles LaTeX to `build/main.pdf`
- **Citation management** — searches Semantic Scholar, fetches real BibTeX, adds to `bibliography.bib`
- **Custom macros & styles** — define in `paper.yaml`, auto-generated on sync
- **Validation** — checks refs, markers, braces, sync status before building
- **Statistics** — word count per section, pages, figures, tables, citations
- **Track changes** — diff PDF with additions/deletions highlighted against any git revision

### Capabilities

Multi-agent workflows you can kick off by asking the agent. These run specialized subagents for research-heavy tasks.

| Capability | What to ask | What it does |
|------------|-------------|--------------|
| Literature review | "Do a lit review on X" | Searches for sources, deep-reads each, synthesizes a themed report with must-cite rankings |
| Claim verification | "Verify the claims in the introduction" | Extracts claims from LaTeX, checks each against prior work, produces per-claim verdicts |
| Source discovery | "Find papers on X" | Quick search — returns a ranked list of relevant sources |
| Source analysis | "Analyze this paper: [URL]" | Deep-reads a single source into a structured card with findings and methodology |
| Peer review | "Start a peer review session" | Interactive — you send notes as you read, agent categorizes and builds a structured feedback report |
| Process peer review | `/process-peer-review reviews/file.md` | Reads a review record, confirms or refutes each item against the paper, applies fixes |
| Spellcheck | `/spellcheck` or `/spellcheck section/01_introduction.tex` | Spelling, grammar, and style check across all sections or a specific file |
| LLM writing detection | "Check if this was written by AI" | Analyzes prose for LLM tells — vocabulary, structure, tone, transitions — produces a per-section detection report |

Reports are written to `capabilities/reports/`. Review records and responses are saved to `reviews/`. See `capabilities/README.md` for full details.

## Starting a Paper

Use the web UI or scaffold a paper manually:

```bash
# Web UI (recommended) — creates papers automatically
./alfred --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY

# Manual scaffold
python3 scripts/scaffold.py /path/to/my-paper --title "My Paper"
```

Then work with the agent:

1. **Tell the agent what to write**: Describe your topic, and optionally specify a conference format (e.g., "NeurIPS", "IEEE", "ACM"). The agent sets up the template, defines sections, and starts writing.
2. **Iterate section by section**: Ask the agent to draft, revise, or expand specific sections. It writes LaTeX content, adds citations from Semantic Scholar, and keeps everything in sync.
3. **Build and review**: Ask the agent to build the PDF. It compiles to `build/main.pdf` and reports any errors.
4. **Check progress**: Ask for stats — the agent reports word counts, page count, figures, tables, and citation counts.
5. **Validate before submitting**: Ask the agent to validate — it checks for broken references, unmatched braces, and sync issues.

The agent handles all the underlying scripts, file management, and LaTeX boilerplate. You just describe what you want.

---

## Conducting a Peer Review

The peer review capability runs as an interactive session — you read the paper and send feedback incrementally, and the agent categorizes each note, maps it to a location, and builds a structured review record.

1. **Start a session**: Say `/peer-review` or "start a peer review session". The agent will read the paper and ask for your name. You can also review external PDFs by providing a path.
2. **Send notes as you read**: Write feedback in natural language. The agent assigns a type (clarity, methodology, claims, etc.), severity (major/minor/nit), and maps it to the relevant section and line. You can also note strengths.
3. **Edit previous notes**: Say "change R3 to major" or "delete R5" to adjust earlier feedback.
4. **Finalize**: Say "done with review" or `/peer-review done`. The agent writes a summary, counts issues by type and severity, and proposes a recommendation (Accept / Minor Revision / Major Revision / Reject) for your confirmation.

Review records are saved to `reviews/` with YAML frontmatter for machine-readable metadata. Run `python3 scripts/reviews.py` to list and summarize past reviews.

---

## Conference Templates

| Template | Description | TeX Live |
|----------|-------------|----------|
| `article` | Plain LaTeX article (default) | Basic |
| `neurips2024` | NeurIPS 2024 | Basic |
| `ieee` | IEEE conference (IEEEtran) | Basic |
| `usenix` | USENIX Security / OSDI / ATC | Basic |
| `acl` | ACL / EMNLP / NAACL | Basic |
| `acm` | ACM conference (acmart sigconf) | Full |

## Structure

The repo is tooling — paper files are created per-paper via `./al` or `scripts/scaffold.py`.

| Path | Purpose |
|------|---------|
| `templates/` | Conference template definitions + bundled .cls/.sty files |
| `styles/` | Optional style packages (messageboxes, codeblocks) |
| `scripts/` | Build, sync, cite, stats, diff, validate, template scripts |
| `capabilities/` | Multi-agent research workflows (lit review, claim verification, etc.) |
| `ui/` | Web UI — FastAPI backend + React/Vite frontend |
| `Taskfile.yml` | Dev tasks — `task test`, `task lint`, `task check` |
| `CLAUDE.md` | Agent instructions (workflow + rules) |
| `AGENT.md` | Detailed how-to for every operation |

## Web UI

A local web interface for interactive paper editing. Terminal-style chat on the left, live PDF preview on the right.

```bash
# Pass an env var name or a raw API key
./alfred --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY
./alfred --model claude-sonnet-4-20250514 --api-key sk-ant-...

# Point at an existing paper directory
./alfred --paper /path/to/paper --model gpt-4o --api-key OPENAI_API_KEY

# Workspace mode — launch in an empty directory for multi-paper support
mkdir workspace && cd workspace
/path/to/alfred/alfred --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY

# Dev mode (frontend hot-reload on port 3000)
./alfred --model claude-sonnet-4-20250514 --api-key ANTHROPIC_API_KEY --dev
```

Opens at `http://localhost:8420`. The agent has access to all scripts, file editing, web search, and capabilities — same as the CLI workflow, but with a visual PDF preview that auto-updates on every build.

Features:
- **Slash commands** — type `/` to see autocomplete for all capabilities and client commands
- **Workspace mode** — paper switcher bar with dropdown and "+ NEW" button when launched without `--paper`
- **Settings popup** — click the model name to change model and API key at runtime
- **Paper title editing** — click the title above the PDF viewer to rename
- **Drag-and-drop PDF** — drop an external PDF onto the viewer to load it (useful for reviewing other papers)
- **Cancel** — press Esc or click CANCEL to stop the agent mid-run
- **Session recovery** — reconnects automatically after network drops, restores chat history
- **Web search** — built-in via DuckDuckGo, no API key needed
- **Any LLM** — works with any model supported by [rigging](https://rigging.dreadnode.io) (Anthropic, OpenAI, Gemini, local models, etc.)

## Requirements

- TeX Live (basic install works for most templates)
- `latexmk` and `biber` (included in basic TeX Live)
- Python 3 with PyYAML (`pip install pyyaml`)
- Node.js 18+ (for web UI frontend)
- Optional: `latexdiff` for diff PDFs (`brew install latexdiff`)

## Development

Requires [Task](https://taskfile.dev) for running dev commands.

```bash
task test          # Run all tests
task lint          # Ruff format check + lint
task fmt           # Auto-format Python
task build         # Build frontend
task check         # fmt + lint + test
```

## Comparison

|  | **ALFRED** | **OpenAI Prism** | **lmms-lab-writer** | **Underleaf** | **PaperDebugger** |
|---|---|---|---|---|---|
| **Approach** | Agent-first — you talk, it writes | Editor with inline AI | Editor with AI agents | Overleaf extension | Overleaf extension |
| **Autonomy** | Full — writes sections, builds, searches, cites | Inline edits, suggestions | AI-assisted editing | Copilot suggestions | Multi-agent patches |
| **LLM support** | Any (Claude, GPT, Gemini, Mistral, local, OpenRouter) | GPT only | Configurable | Locked to their API | Configurable |
| **Runs locally** | Yes — nothing leaves your machine | No (cloud) | Yes | No (cloud) | No (cloud) |
| **Research workflows** | Lit review, claim verification, peer review, source analysis | No | No | Citation search, summarization | Literature retrieval |
| **PDF preview** | Live auto-reload | Yes | Yes | Via Overleaf | Via Overleaf |
| **Conference templates** | 6 built-in (NeurIPS, IEEE, ACM, USENIX, ACL, article) | Yes | Auto-detect | Via Overleaf | Via Overleaf |
| **Web search** | Built-in (DuckDuckGo) | Via ChatGPT | No | No | No |
| **PDF/image to LaTeX** | No | No | No | Yes | No |
| **Cost** | Free (bring your own API key) | Free | Free | Freemium (usage limits) | Free |
| **Requires Overleaf** | No | No | No | Yes | Yes |
