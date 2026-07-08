# agentic-latex

A scaffold for AI-agent-driven LaTeX document authoring. Clone the repo, point an AI coding agent at it, give it a topic — it writes the paper.

## How It Works

The repo is structured so any coding agent (Claude Code, Cursor, GPT, etc.) can immediately understand and operate it:

- **`paper.yaml`** is the source of truth — title, authors, sections, macros, template. The agent edits this file to define the paper structure.
- **`scripts/sync.py`** reads `paper.yaml` and updates `main.tex` automatically — the agent never hand-edits LaTeX boilerplate.
- **`section/*.tex`** files are where the agent writes actual content, one section at a time.
- **`CLAUDE.md`** and **`AGENT.md`** tell the agent exactly how to use every tool, in what order, and what rules to follow.

The agent workflow: pick a template → define sections in `paper.yaml` → sync → write content → add citations → build → check stats → iterate.

## Starting a Paper

1. **Pick a template**: Run `python3 scripts/init_template.py <name>` (e.g., `neurips2024`, `ieee`, `acm`) or set `template:` in `paper.yaml` directly. Use `article` for a plain LaTeX document.
2. **Define your paper**: Fill in `title`, `authors`, and `abstract_summary` in `paper.yaml`. Add your sections under `sections:` — each gets a numbered `.tex` file.
3. **Sync**: Run `python3 scripts/sync.py` to generate `main.tex` and create the `section/*.tex` files.
4. **Write**: Edit each `section/*.tex` file — one section at a time. Use one sentence per line for clean diffs.
5. **Add citations**: Search with `python3 scripts/cite.py search "query"`, then add with `python3 scripts/cite.py add <ID>`. Use `\cite{key}` in your section files.
6. **Build**: Run `bash scripts/build.sh` to compile to `build/main.pdf`. Check `build/main.log` if there are errors.
7. **Check progress**: Run `python3 scripts/stats.py` for word counts, page count, figures, and tables.
8. **Validate**: Run `bash scripts/validate.sh` before finalizing to catch broken refs, unmatched braces, and sync drift.

Or just tell the agent what you want to write about — it knows these steps and will handle them for you.

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

Reports are written to `capabilities/reports/`. See `capabilities/README.md` for full details.

### Conducting a Peer Review

The peer review capability runs as an interactive session — you read the paper and send feedback incrementally, and the agent categorizes each note, maps it to a location, and builds a structured review record.

1. **Start a session**: Say `/peer-review` or "start a peer review session". The agent will read the paper and ask for your name. You can also review external PDFs by providing a path.
2. **Send notes as you read**: Write feedback in natural language. The agent assigns a type (clarity, methodology, claims, etc.), severity (major/minor/nit), and maps it to the relevant section and line. You can also note strengths.
3. **Edit previous notes**: Say "change R3 to major" or "delete R5" to adjust earlier feedback.
4. **Finalize**: Say "done with review" or `/peer-review done`. The agent writes a summary, counts issues by type and severity, and proposes a recommendation (Accept / Minor Revision / Major Revision / Reject) for your confirmation.

Review records are saved to `reviews/` with YAML frontmatter for machine-readable metadata. Run `python3 scripts/reviews.py` to list and summarize past reviews.

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

| Path | Purpose |
|------|---------|
| `paper.yaml` | Paper manifest — title, authors, sections, macros, template |
| `main.tex` | Main document (managed by sync + templates) |
| `section/` | Ordered section files where content is written |
| `bibliography.bib` | BibTeX references |
| `templates/` | Conference template definitions + bundled .cls/.sty files |
| `styles/` | Optional style packages (messageboxes, codeblocks) |
| `scripts/` | Build, sync, cite, stats, diff, validate, template scripts |
| `capabilities/` | Multi-agent research workflows (lit review, claim verification, etc.) |
| `CLAUDE.md` | Agent instructions (workflow + rules) |
| `AGENT.md` | Detailed how-to for every operation |

## Requirements

- TeX Live (basic install works for most templates)
- `latexmk` and `biber` (included in basic TeX Live)
- Python 3 with PyYAML (`pip install pyyaml`)
- Optional: `latexdiff` for diff PDFs (`brew install latexdiff`)
