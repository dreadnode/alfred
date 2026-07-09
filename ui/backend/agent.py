"""Dreadnode agent factory for agentic-latex paper editing."""

import os

import yaml

from dreadnode.agent import TaskAgent
from dreadnode.agent.hooks.summarize import summarize_when_long
from dreadnode.agent.tools.execute import command
from dreadnode.agent.tools.fs import Filesystem

from .tools import make_latex_tools, make_web_search, web_fetch


def _load_paper_context(paper_dir: str) -> str:
    """Read ``paper.yaml`` and format a concise summary of the current paper state.

    Args:
        paper_dir: Absolute path to the paper working directory.

    Returns:
        Formatted string describing title, authors, template, and section statuses.
        Returns an empty string if ``paper.yaml`` is missing or unreadable.
    """
    yaml_path = os.path.join(paper_dir, "paper.yaml")
    if not os.path.isfile(yaml_path):
        return ""

    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
    except Exception:
        return ""

    if not isinstance(data, dict):
        return ""

    lines: list[str] = ["## Current Paper State (from paper.yaml)"]
    lines.append(f"- Title: {data.get('title', 'Untitled')}")
    lines.append(f"- Template: {data.get('template', 'unknown')}")

    authors = data.get("authors", [])
    if authors:
        names = ", ".join(a.get("name", "?") for a in authors if isinstance(a, dict))
        lines.append(f"- Authors: {names}")

    abstract = data.get("abstract_summary", "")
    if abstract:
        lines.append(f"- Abstract: {abstract}")

    sections = data.get("sections", [])
    if sections:
        lines.append("- Sections:")
        for sec in sections:
            if isinstance(sec, dict):
                slug = sec.get("slug", "?")
                title = sec.get("title", "?")
                status = sec.get("status", "?")
                lines.append(f"  - [{status}] {slug} — {title}")

    macros = data.get("macros")
    if isinstance(macros, dict) and macros:
        lines.append(f"- Macros defined: {', '.join(macros.keys())}")

    styles = data.get("styles")
    if isinstance(styles, list) and styles:
        lines.append(f"- Style packages: {', '.join(str(s) for s in styles)}")

    return "\n".join(lines)


def create_agent(
    model: str,
    paper_dir: str,
    api_key_env: str | None = None,
    search_api_key_env: str | None = None,
) -> TaskAgent:
    """Create and configure a LaTeX editing agent.

    Args:
        model: LLM model identifier (e.g. ``claude-sonnet-4-20250514``).
        paper_dir: Absolute path to the paper working directory.
        api_key_env: Name of the environment variable holding the LLM API key.
            If provided, the variable must be set and non-empty.
        search_api_key_env: Name of the env-var holding the Tavily web search
            API key. If ``None`` or unset, ``web_search`` returns a fallback message.

    Returns:
        A configured ``TaskAgent`` with filesystem, shell, web, and LaTeX tools.

    Raises:
        ValueError: If ``api_key_env`` is specified but the variable is unset.
    """
    if api_key_env and not os.environ.get(api_key_env):
        raise ValueError(f"Environment variable '{api_key_env}' is not set or empty")

    fs = Filesystem(path=paper_dir, variant="write")
    latex_tools = make_latex_tools(paper_dir)
    search_tool = make_web_search(search_api_key_env)
    paper_context = _load_paper_context(paper_dir)

    instructions = f"""\
You are an expert LaTeX paper editing agent. You help users write, edit, and build academic papers.

## Working Directory
The paper is located at: {paper_dir}

## Project Structure
```
paper.yaml              # Source of truth — read this first
main.tex                # Main document (managed by sync + templates)
bibliography.bib        # BibTeX references
section/                # Ordered section files (00_abstract.tex, 01_introduction.tex, ...)
templates/              # Conference template definitions + .cls/.sty files
data/                   # CSV/data files for tables and figures
figures/                # Images and generated figures
styles/                 # Optional .sty packages (messageboxes, codeblocks)
scripts/                # Build, sync, validation, and template scripts
reviews/                # Peer review records
capabilities/           # Extended agent workflows (lit-review, verify-claims, etc.)
build/                  # Output directory (main.pdf, diff.pdf)
```

## Core Workflows
1. **Edit content**: Modify .tex files in section/ (one section per file)
2. **Build PDF**: build_paper compiles LaTeX to build/main.pdf
3. **Sync config**: After editing paper.yaml, sync_paper updates main.tex
4. **Validate**: validate_paper checks refs, markers, braces, sync status
5. **Citations**: search_citations to find papers, add_citation to add them
6. **Stats**: paper_stats for word count, pages, figures, tables
7. **Diff**: generate_diff creates a track-changes PDF vs a git revision
8. **Templates**: list_templates to see options, switch_template to change
9. **Reviews**: list_reviews to see peer review records

## Rules
- paper.yaml is the source of truth — edit it first, then sync
- Edit content in section/*.tex files, never in main.tex body directly
- Never hand-edit regions between % BEGIN SYNC / % END SYNC markers
- Use one sentence per line in .tex source for clean diffs
- After making edits, build the PDF so the user can see changes
- Always report what you changed and the build result

## Conventions
- Section files use numbered prefixes: 00_, 01_, ..., 07_
- Labels: sec:slug, fig:label, tab:label, eq:label, alg:label
- Use booktabs for tables (\\toprule, \\midrule, \\bottomrule, no vertical rules)
- Prefer vector graphics (PDF/SVG) over raster (PNG/JPG) for diagrams
- Use \\cite{{key}} for citations, \\ref{{sec:slug}} for cross-references

## Macros and Styles
- Add macros to paper.yaml under macros: (e.g. NumSamples: "1{{,}}000") then sync
- Add style packages to paper.yaml under styles: then sync
  - messageboxes — colored tcolorbox: systemprompt, userprompt, assistantresponse, warningbox, infobox
  - codeblocks — styled code listings: codeblock environment, \\inlinecode{{}}

## Common Build Errors
- **Undefined control sequence**: Missing \\usepackage{{}} or typo
- **Missing file**: Check \\input{{}} path matches actual filename
- **Missing \\item**: Forgot \\item inside itemize/enumerate
- **Runaway argument**: Unmatched brace — run validate_paper
- **Citation undefined**: Run build twice, or check bibliography.bib for the key

## Capabilities (Advanced Workflows)
When the user triggers one of these, read the corresponding skill.md file and follow
its workflow using your available tools (filesystem, web_fetch, web_search, command).
Also read any shared guidance files referenced by the skill.md (in capabilities/shared/).

| Trigger | Skill File | Description |
|---------|-----------|-------------|
| /search-sources "query" | capabilities/search-sources/skill.md | Find relevant papers and sources |
| /analyze-source <URL> "context" | capabilities/analyze-source/skill.md | Deep-read a single source |
| /lit-review "topic" | capabilities/lit-review/skill.md | Full literature review workflow |
| /verify-claims section/file.tex | capabilities/verify-claims/skill.md | Verify claims against evidence |
| /peer-review | capabilities/peer-review/skill.md | Interactive peer review session |

Natural-language triggers also work:
- "find papers about..." or "search for sources on..." → search-sources
- "summarize this paper..." or "analyze this source..." → analyze-source
- "literature review on..." or "find related work for..." → lit-review
- "check claims in..." or "verify claims..." → verify-claims
- "review my paper..." or "give feedback on..." → peer-review

If web_search is unavailable (no API key), use search_citations for academic sources
and web_fetch for known URLs.

{paper_context}
"""

    return TaskAgent(
        name="latex-agent",
        description="An agent that helps write and edit LaTeX academic papers",
        model=model,
        instructions=instructions,
        max_steps=50,
        tools=[command, fs, web_fetch, search_tool, *latex_tools],
        hooks=[summarize_when_long(max_tokens=100_000, min_messages_to_keep=6)],
    )
