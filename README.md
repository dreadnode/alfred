# agentic-latex

A scaffold for AI-agent-driven LaTeX document authoring. Clone the repo, point an AI coding agent at it, give it a topic — it writes the paper.

## How It Works

The repo is structured so any coding agent (Claude Code, Cursor, GPT, etc.) can immediately understand and operate it:

- **`paper.yaml`** is the source of truth — title, authors, sections, macros, template. The agent edits this file to define the paper structure.
- **`scripts/sync.py`** reads `paper.yaml` and updates `main.tex` automatically — the agent never hand-edits LaTeX boilerplate.
- **`section/*.tex`** files are where the agent writes actual content, one section at a time.
- **`CLAUDE.md`** and **`AGENT.md`** tell the agent exactly how to use every tool, in what order, and what rules to follow.

The agent workflow: pick a template → define sections in `paper.yaml` → sync → write content → add citations → build → check stats → iterate.

## Features

### Writing & Building

| Feature | Command | Description |
|---------|---------|-------------|
| Template switching | `python3 scripts/init_template.py neurips2024` | Switch between 6 conference formats |
| YAML-driven sync | `python3 scripts/sync.py` | Sync paper.yaml → main.tex automatically |
| PDF build | `bash scripts/build.sh` | Compile LaTeX → `build/main.pdf` |
| Custom macros | Define in `paper.yaml` under `macros:` | Auto-generates `\newcommand` entries |
| Style packages | Define in `paper.yaml` under `styles:` | Message boxes, code blocks |

### Research & Citations

| Feature | Command | Description |
|---------|---------|-------------|
| Citation search | `python3 scripts/cite.py search "query"` | Search Semantic Scholar for papers |
| Citation add | `python3 scripts/cite.py add arXiv:1706.03762` | Fetch BibTeX and add to bibliography |
| Literature review | `/lit-review "topic"` | Multi-agent search → analyze → synthesize → report |
| Source discovery | `/search-sources "query"` | Quick reconnaissance — find relevant papers |
| Source analysis | `/analyze-source <URL> "context"` | Deep-read a single paper into structured card |

### Quality & Validation

| Feature | Command | Description |
|---------|---------|-------------|
| Claim verification | `/verify-claims section/01_introduction.tex` | Verify paper claims against prior work |
| Peer review | `/peer-review` | Interactive review session — record notes into structured report |
| Validation | `bash scripts/validate.sh` | Check refs, markers, braces, sync status |
| Statistics | `python3 scripts/stats.py` | Word count, pages, figures, tables, citations |
| Track changes | `python3 scripts/diff.py [rev]` | Diff PDF with additions/deletions highlighted |

## Quick Start

```bash
# Switch to a conference template
python3 scripts/init_template.py neurips2024

# Sync paper.yaml → main.tex (after editing paper.yaml)
python3 scripts/sync.py

# Build the PDF
bash scripts/build.sh

# Search and add citations from Semantic Scholar
python3 scripts/cite.py search "transformer attention"
python3 scripts/cite.py add arXiv:1706.03762

# Paper statistics (word count, pages, figures, tables)
python3 scripts/stats.py

# Generate track-changes diff PDF against last commit
python3 scripts/diff.py

# Validate sources
bash scripts/validate.sh
```

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
