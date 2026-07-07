# Agent Instructions for LaTeX Paper Authoring

This repository is a template for AI-agent-driven LaTeX document creation. Follow these instructions when working on this project.

## Project Structure

```
├── paper.yaml              # Source of truth for paper structure — read this first
├── main.tex                # Main document (managed by sync + templates)
├── bibliography.bib        # BibTeX references
├── section/                # Ordered section files (00_abstract.tex, 01_introduction.tex, ...)
├── templates/              # Conference template definitions + .cls/.sty files
├── data/                   # CSV/data files for tables and figures
├── figures/                # Images and generated figures
├── styles/                 # Optional .sty packages (messageboxes, codeblocks)
├── scripts/                # Build, sync, validation, and template scripts
├── reviews/                # Peer review records (tracked in git)
├── .latexmkrc              # Build engine configuration
└── build/                  # Output directory (gitignored)
```

## Key Workflows

### Reading the paper state

1. Read `paper.yaml` to understand title, authors, sections, and their status
2. Read individual `section/*.tex` files to see content
3. Look for `\tbd{}`, `\note{}`, and `\todo{}` markers for incomplete areas

### Writing content

1. Edit section files in `section/` — never write raw LaTeX in main.tex body
2. Use `\label{sec:slug}` and `\ref{sec:slug}` for cross-references
3. Use `\cite{key}` for citations — add entries to `bibliography.bib`
4. After writing, update `paper.yaml` section status (draft → in_progress → complete)

### Switching conference templates

List available templates:
```bash
python3 scripts/init_template.py --list
```

Switch to a template:
```bash
python3 scripts/init_template.py neurips2024
```

This copies the template's `main.tex` and style files to the project root, updates `paper.yaml`, and runs sync.

Available templates: `article` (default), `neurips2024`, `ieee`, `acm` (requires full TeX Live), `usenix`, `acl`.

### Adding a new section

1. Add the section entry to `paper.yaml` under `sections:` in the desired position
2. Run `python3 scripts/sync.py` — this updates `main.tex` and creates the `.tex` file
3. Use decimal prefixes for insertion (e.g., `065_` goes between `06_` and `07_`)

### Adding figures

1. Place image files in `figures/`
2. Reference with:
```latex
\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.8\textwidth]{figures/filename}
  \caption{Description.}
  \label{fig:label}
\end{figure}
```

### Adding tables

1. For data-driven tables, place source data in `data/`
2. Use `booktabs` style:
```latex
\begin{table}[htbp]
  \centering
  \caption{Description.}
  \label{tab:label}
  \begin{tabular}{lcc}
    \toprule
    Header & Col A & Col B \\
    \midrule
    Row 1 & val & val \\
    Row 2 & val & val \\
    \bottomrule
  \end{tabular}
\end{table}
```

### Adding custom macros

1. Add to `paper.yaml` under `macros:` (e.g., `NumModels: "5"`)
2. Run `python3 scripts/sync.py` — generates `\newcommand{\NumModels}{5}` in `main.tex`
3. Use for frequently repeated values (dataset sizes, model names, etc.)

### Enabling style packages

1. Add the package name to `paper.yaml` under `styles:` (e.g., `- messageboxes`)
2. Run `python3 scripts/sync.py`
3. Available packages:
   - `messageboxes` — colored tcolorbox environments: `systemprompt`, `userprompt`, `assistantresponse`, `warningbox`, `infobox`, `graybox`
   - `codeblocks` — styled code listings: `codeblock` environment, `\inlinecode{}`, language presets

### Syncing paper.yaml → main.tex

Run: `python3 scripts/sync.py`
Preview: `python3 scripts/sync.py --dry-run`

This updates all `% BEGIN SYNC` / `% END SYNC` regions in `main.tex` to match `paper.yaml`. Never hand-edit these regions — they will be overwritten on next sync.

Synced regions: metadata (title/authors), macros, styles, bibliography, sections, author-block (template-dependent).

### Adding citations

Search for papers:
```bash
python3 scripts/cite.py search "transformer attention mechanism"
```

Add a paper by ID (Semantic Scholar ID, DOI, or arXiv ID):
```bash
python3 scripts/cite.py add arXiv:1706.03762
```

Search and auto-add the top result:
```bash
python3 scripts/cite.py search --add "BERT pre-training"
```

This fetches real BibTeX from Semantic Scholar and appends it to `bibliography.bib`. Use `\cite{key}` in your section files to reference it.

### Checking paper statistics

Run: `python3 scripts/stats.py`
JSON: `python3 scripts/stats.py --json`

Reports word count per section, total pages, figure/table/citation/equation counts. Use this to check if sections are too short or the paper exceeds a page limit.

### Generating a diff PDF

```bash
python3 scripts/diff.py           # diff against last commit
python3 scripts/diff.py HEAD~3    # diff against 3 commits ago
python3 scripts/diff.py abc123    # diff against specific commit
```

Produces `build/diff.pdf` with additions in blue and deletions in red strikethrough. Requires `latexdiff` (`brew install latexdiff`).

### Building the document

Run: `./scripts/build.sh`
Clean: `./scripts/build.sh --clean`

The build uses `latexmk` with pdflatex + biber. Output goes to `build/main.pdf`.

### Validating

Run: `./scripts/validate.sh`

This checks:
- All `\input{}` references point to existing files
- Draft markers (`\tbd{}`, `\note{}`, `\todo{}`)
- Brace matching
- chktex lint (if installed)

## Capabilities

Extended agent capabilities beyond core document authoring. Full documentation in `capabilities/README.md`.

### Trigger Recognition

These capabilities can be invoked explicitly (e.g., `/lit-review "topic"`) or recognized from natural-language requests. When the user's message matches a trigger pattern below, activate the corresponding capability by reading its `skill.md` and following the documented workflow.

| Capability | Trigger Patterns | Skill Definition |
|------------|-----------------|------------------|
| **lit-review** | `/lit-review`, "literature review", "find related work", "survey papers on", "what papers exist about" | `capabilities/lit-review/skill.md` |
| **verify-claims** | `/verify-claims`, "verify claims", "check claims", "fact-check", "are these claims supported" | `capabilities/verify-claims/skill.md` |
| **search-sources** | `/search-sources`, "search for sources", "find papers about", "search for papers" | `capabilities/search-sources/skill.md` |
| **analyze-source** | `/analyze-source`, "analyze this source", "summarize this paper", "read this paper" | `capabilities/analyze-source/skill.md` |
| **peer-review** | `/peer-review`, "peer review", "review this paper", "start a review session", "review my paper", "give feedback on the paper" | `capabilities/peer-review/skill.md` |

When a trigger is matched:
1. Read the corresponding `skill.md` for the full workflow
2. Read any guidance documents listed in the skill (e.g., shared config, output formats)
3. Follow the session lifecycle defined in the skill

If ambiguous (e.g., "review" could mean peer-review or code review), ask the user to clarify.

### Literature review

```
/lit-review "your research topic"
```

Launches Searcher → Analyzer → Synthesizer agents to produce a themed review with must-cite/should-cite/nice-to-have rankings. The report is written to `capabilities/reports/` and a summary is printed to stdout.

The skill automatically reads `paper.yaml` and `bibliography.bib` for context — it knows the paper's structure and excludes already-cited works from results.

### Claim verification

```
/verify-claims section/01_introduction.tex
```

Auto-extracts claims from LaTeX, routes each to the appropriate verification strategy (direct source lookup for prior-work claims, adversarial search for superlatives, arithmetic check for comparatives), and produces a per-claim verdict report (Supported / Partially Supported / Unsupported / Contested / Contradicted).

The skill reads `bibliography.bib` to resolve `\cite{key}` references to DOIs/URLs for direct source verification.

### Source discovery and analysis

```
/search-sources "query"          # Quick source discovery (no deep analysis)
/analyze-source <URL> "context"  # Deep-read a single source into a structured card
```

### Adding discovered sources to the paper

After a review identifies must-cite sources, add them to the bibliography:

```bash
python3 scripts/cite.py add arXiv:1706.03762
python3 scripts/cite.py search --add "paper title"
```

Then use `\cite{key}` in the relevant section files.

### Peer review

```
/peer-review
/peer-review --reviewer "Alice Chen"
/peer-review --reviewer "Alice Chen" section/03_methodology.tex
```

Interactive review session. The reviewer reads the paper and sends notes — the agent categorizes each (clarity, methodology, claims, etc.), assigns severity (major/minor/nit), maps it to the relevant file:line, and appends it to a running review record.

Review records are saved to `reviews/<paper-slug>-<reviewer-slug>-<timestamp>.md` and committed to the repo, so all reviews are tracked over time. The agent asks for the reviewer's name if not provided via `--reviewer`.

Finalize with "done with review" or `/peer-review done` — the agent writes a summary, counts issues by type/severity, and suggests a recommendation (accept/minor revision/major revision/reject). The reviewer confirms or adjusts before the report is closed.

If a note questions a specific claim, the agent can optionally run verify-claims or search-sources to check it.

## Error Handling

When a build fails:
1. Read `build/main.log` for the error
2. Common fixes:
   - **Undefined control sequence**: Missing `\usepackage{}` or typo in command name
   - **Missing file**: Check `\input{}` path matches actual filename
   - **Missing \item**: Forgot `\item` inside `itemize`/`enumerate`
   - **Runaway argument**: Unmatched brace — run `./scripts/validate.sh`
   - **Citation undefined**: Run build twice, or check `bibliography.bib` for the key

## Conventions

- Section files use numbered prefixes: `00_`, `01_`, ..., `07_`
- Labels follow pattern: `sec:`, `fig:`, `tab:`, `eq:`, `alg:`
- Use `\cref{}` (from cleveref, if enabled) or `\ref{}` for cross-references
- Use `booktabs` for tables (no vertical rules, use `\toprule`, `\midrule`, `\bottomrule`)
- Prefer vector graphics (PDF/SVG) over raster (PNG/JPG) for diagrams
- Keep one sentence per line in .tex source for clean diffs
