# ALFRED

![Version](https://img.shields.io/badge/version-0.5.0-008080) ![Python](https://img.shields.io/badge/python-3.10%2B-008080) ![Node](https://img.shields.io/badge/node-20%2B-008080) ![License](https://img.shields.io/badge/license-MIT-008080)

**A**gentic **L**atex **f**or **R**esearch, **E**diting, and **D**rafting.

![ALFRED web UI](docs/alfred-ss.png)

## Features

### Built-in

The agent handles these automatically as part of the writing workflow — just tell it what you want.

- **Conference templates** — 14 formats, including current NeurIPS, ICLR, ICML, CVPR, AAAI, LNCS, and NDSS kits
- **Citation management** — searches Semantic Scholar, fetches BibTeX, and adds citations to your bibliography
- **Custom macros & styles** — the agent defines and manages LaTeX macros and style packages automatically
- **Validation** — catches broken references, unmatched braces, and other LaTeX errors before building
- **Track changes** — generates a highlighted diff PDF against any git revision
- **PDF dark mode** — toggle for comfortable nighttime reading
- **Token usage tracker** — live input/output token counts in the header
- **Multi-session tabs** — each paper gets its own session tab with independent chat and PDF viewer
- **Session persistence** — chat history and agent context survive refreshes, reconnects, and server restarts
- **Per-session model switching** — change the LLM model for any session without losing conversation context
- **Notepad** — markdown note-taking view that swaps with the chat pane, auto-saves per paper
- **Image to LaTeX** — drop, paste, or upload an image of an equation, table, or diagram and the agent converts it to LaTeX

### Capabilities

Multi-agent research workflows — type `/` in the chat to see all commands.

| Command | Description |
|---------|-------------|
| `/lit-review "topic"` | Search for sources, deep-read each, synthesize a themed report with must-cite rankings |
| `/search-sources "query"` | Quick source discovery — ranked list of relevant papers |
| `/analyze-source <URL>` | Deep-read a single source into a structured card with findings and methodology |
| `/verify-claims section/file.tex` | Extract claims from LaTeX, check each against prior work, produce per-claim verdicts |
| `/peer-review` | Interactive review session — send notes as you read, agent categorizes and builds a structured report |
| `/process-peer-review [file]` | Process a peer review record — confirm or refute each item, apply fixes |
| `/spellcheck [file]` | Spelling, grammar, and style check across all sections or a specific file |
| `/detect-llm-writing [file]` | Analyze prose for LLM writing indicators — vocabulary, structure, tone, transitions |

Reports are written to `capabilities/reports/`. Review records are saved to `reviews/`.

## Installation

### Prerequisites

- **Python 3.10+**
- **Node.js 20+**
- **TeX Live** (basic install works for most templates — includes `latexmk` and `biber`)
- **[uv](https://docs.astral.sh/uv/)** (used by the launcher for venv setup)
- Optional: `latexdiff` for track-changes PDFs (`brew install latexdiff` on macOS)

### Setup

```bash
git clone https://github.com/dreadnode/alfred.git
cd alfred
./alfred --model claude-sonnet-4-20250514 --api-key-env ANTHROPIC_API_KEY
```

On first run, the launcher automatically:
1. Creates a Python venv and installs backend dependencies
2. Installs frontend dependencies (`npm ci`) and builds the UI
3. Opens the web UI at `http://localhost:8420`

No manual `pip install` or `npm install` needed.

### API Keys

Set the API key in an environment variable and pass its name:

```bash
./alfred --model openai/gpt-5.6-sol --api-key-env OPENAI_API_KEY
```

Works with any model supported by [rigging](https://rigging.dreadnode.io) — Anthropic, OpenAI, Google, Mistral, local models via Ollama, or any provider via OpenRouter.

## Starting a Paper

Launch the UI and create sessions from the tab bar:

```bash
# Launch — multi-session by default, papers stored in ./papers/
./alfred --model openai/gpt-5.6-sol --api-key-env OPENAI_API_KEY

# Pre-create a session for an existing paper
./alfred --paper /path/to/my-paper --model openai/gpt-5.6-sol --api-key-env OPENAI_API_KEY

# Manual scaffold (without the UI)
python3 scripts/scaffold.py /path/to/my-paper --title "My Paper"
```

In the UI, click **+ NEW** to create a session, then ask the agent to create a paper (e.g., "create a new paper about X"). Each session gets its own tab with independent chat history and PDF viewer.

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

Conference templates default to the venue's anonymous submission mode where
the official kit provides one. The generated author metadata remains in the
source so it can be enabled for preprints or camera-ready papers using the
documented class/style option.

| Template | Description | Default mode |
|----------|-------------|--------------|
| `article` | Plain LaTeX article | Draft |
| `neurips` | Current NeurIPS kit (stable alias for `neurips2026`) | Submission |
| `neurips2026` | NeurIPS 2026 | Submission |
| `neurips2024` | NeurIPS 2024 (legacy compatibility) | Preprint |
| `iclr2026` | ICLR 2026 | Submission |
| `icml2026` | ICML 2026 | Submission |
| `cvpr2026` | CVPR 2026 | Review |
| `aaai2026` | AAAI 2026 | Submission |
| `lncs` | Springer Lecture Notes in Computer Science | Proceedings |
| `ndss2026` | NDSS Symposium 2026 | Submission |
| `ieee` | Generic IEEE conference (IEEEtran) | Proceedings |
| `usenix` | USENIX Security / OSDI / ATC | Proceedings |
| `acl` | ACL / EMNLP / NAACL | Proceedings |
| `acm` | ACM conference (acmart `sigconf`) | Proceedings |

TeX Live Full is recommended for conference templates because official style
files can depend on packages outside a basic TeX installation.
Upstream provenance and refresh links are recorded in
[`templates/SOURCES.md`](templates/SOURCES.md).

## Security

ALFRED runs an LLM agent with access to your local filesystem and shell.
These mitigations are in place, but they are **defense-in-depth, not a
sandbox**:

- **Command denylist** — network-exfiltration binaries (`curl`, `wget`,
  `nc`, `ssh`, etc.) and env-exposure commands (`env`, `printenv`) are
  blocked, including when wrapped in `bash -c`. The agent can still run
  arbitrary commands through other interpreters.
- **Environment scrubbing** — credential-shaped environment variables
  (`*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, and AWS keys) are
  stripped from the agent's arbitrary `command` tool. Fixed workflow
  tools (build, sync, cite) inherit the full environment because they
  run hardcoded trusted scripts.
- **SSRF protection** — `web_fetch` validates URLs against
  internal/private address ranges and manually follows redirects with
  per-hop validation.
- **Build isolation** — `latexmk` runs with `-norc` to prevent
  `.latexmkrc` Perl code execution from untrusted paper directories.

**Recommendations:**

- Do not run ALFRED with highly privileged credentials or on sensitive
  infrastructure against untrusted paper directories.
- Use dedicated, low-privilege API keys where possible.
- Review `paper.yaml` and any `.latexmkrc` files before opening papers
  from untrusted sources.

## Development

Requires [Task](https://taskfile.dev) for running dev commands.

```bash
task test          # Run all tests
task lint          # Ruff format check + lint
task fmt           # Auto-format Python
task build         # Build frontend
task check         # fmt + lint + test
```

## Comparison to other tools

There are several great projects bringing AI to academic writing — each with a different approach.

|  | **ALFRED** | **OpenAI Prism** | **lmms-lab-writer** | **Underleaf** | **PaperDebugger** |
|---|---|---|---|---|---|
| **Approach** | Agent-first — you talk, it writes | Editor with inline AI | Desktop editor with embedded AI (OpenCode) | Chrome extension for Overleaf + standalone web app | Chrome extension for Overleaf |
| **Autonomy** | Full — writes sections, builds, searches, cites | Inline edits, agent-assisted citations | AI-assisted editing (general-purpose agent) | 60+ one-shot tools (generate, convert, rewrite) | Multi-agent patches |
| **LLM support** | Any (Claude, GPT, Gemini, Mistral, local, OpenRouter) | GPT only | Any via OpenCode (Claude, GPT, Gemini, DeepSeek, local) | Locked to their API (OpenAI, no model choice) | Configurable |
| **Runs locally** | Yes — server is local; content is sent to configured LLM provider and optional search APIs | No (cloud) | Yes — native desktop app (Tauri), fully offline capable | No (cloud SaaS, content routed through their servers) | Cloud (self-host option) |
| **Research workflows** | Lit review, claim verification, peer review, source analysis | Lit search, citations | No | Citation search (arXiv) | Literature retrieval |
| **PDF preview** | Live auto-reload | Yes | Yes, with SyncTeX (bidirectional source ↔ PDF) | Via Overleaf (or snippet preview in web app) | Via Overleaf |
| **Conference templates** | 14 built-in formats | Yes | No | Yes (NeurIPS, ICML, ACL, IEEE + reformatter) | Via Overleaf |
| **Web search** | Built-in (Tavily / Brave / DuckDuckGo) | Built-in (literature) | No | No | No |
| **PDF/image to LaTeX** | Yes (image to LaTeX) | Yes | No | Yes — flagship feature (OCR-optimized, handwriting, PDF, Snip tool) | No |
| **Git integration** | No | No | Yes — built-in staging, commits, diffs, GitHub publish | No | No |
| **LaTeX distribution** | Requires TeX Live | N/A | Auto-detects or installs TinyTeX, auto-installs missing packages | Via Overleaf (no local compilation) | Via Overleaf |
| **Cost** | Free (bring your own API key) | Free | Free (bring your own API key) | Freemium — free 10 credits/mo, $5–10/mo for more | Free |
| **Open source** | Yes (MIT) | No | Yes (MIT) | No (closed source) | No |
