"""LaTeX script tools — each closes over paper_dir."""

import asyncio
import os
import typing as t

from dreadnode.agent.tools import AnyTool, tool

from .subprocess import run_script


def make_latex_tools(paper_dir: str) -> list[AnyTool]:
    """Create LaTeX-specific tools that close over ``paper_dir``.

    Each returned tool captures ``paper_dir`` in its closure so the LLM
    never needs to supply it as an argument.

    Args:
        paper_dir: Absolute path to the paper working directory.

    Returns:
        List of tool objects ready to be passed to an Agent.
    """

    @tool(catch=True)
    async def build_paper() -> str:
        """Build the LaTeX paper to PDF.

        Runs ``scripts/build.sh`` and returns the build output.
        If the build fails, appends relevant error lines from ``build/main.log``.
        """
        try:
            return await run_script("bash", "scripts/build.sh", cwd=paper_dir, timeout=120)
        except RuntimeError as exc:
            log_path = os.path.join(paper_dir, "build", "main.log")
            extra = ""
            if os.path.exists(log_path):
                with open(log_path) as f:
                    lines = f.readlines()
                errors = [line.rstrip() for line in lines if line.startswith("!") or "Error" in line]
                if errors:
                    extra = "\n\n--- Build Errors ---\n" + "\n".join(errors[:20])
            raise RuntimeError(f"{exc}{extra}") from exc

    @tool(catch=True)
    async def sync_paper() -> str:
        """Sync ``paper.yaml`` to ``main.tex`` — run after editing paper.yaml."""
        return await run_script("python3", "scripts/sync.py", cwd=paper_dir)

    @tool(catch=True)
    async def validate_paper() -> str:
        """Validate the paper — checks refs, markers, braces, sync status.

        Returns output regardless of exit code because the script reports
        validation issues via non-zero return codes, not failures.
        """
        proc = await asyncio.create_subprocess_exec(
            "bash", "scripts/validate.sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=paper_dir,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return stdout.decode(errors="replace")

    @tool(catch=True)
    async def search_citations(
        query: t.Annotated[str, "Search query for Semantic Scholar"],
    ) -> str:
        """Search for academic citations using Semantic Scholar."""
        return await run_script("python3", "scripts/cite.py", "search", query, cwd=paper_dir)

    @tool(catch=True)
    async def add_citation(
        citation_id: t.Annotated[str, "Citation ID from search results to add"],
    ) -> str:
        """Add a citation to ``bibliography.bib`` by its ID."""
        return await run_script("python3", "scripts/cite.py", "add", citation_id, cwd=paper_dir)

    @tool(catch=True)
    async def paper_stats() -> str:
        """Get paper statistics — word count, pages, figures, tables."""
        return await run_script("python3", "scripts/stats.py", cwd=paper_dir, timeout=15)

    @tool(catch=True)
    async def generate_diff(
        revision: t.Annotated[str, "Git revision to diff against (e.g. HEAD, HEAD~3, commit hash)"] = "HEAD",
    ) -> str:
        """Generate a track-changes PDF diffing current source against a git revision.

        Output is written to ``build/diff.pdf`` with additions in blue and
        deletions in red strikethrough. Requires ``latexdiff`` to be installed.
        """
        return await run_script("python3", "scripts/diff.py", revision, cwd=paper_dir, timeout=120)

    @tool(catch=True)
    async def switch_template(
        template_name: t.Annotated[str, "Template name (e.g. neurips2024, ieee, acm, usenix, acl, article)"],
    ) -> str:
        """Switch the paper to a different conference template.

        Copies template files, updates ``paper.yaml``, and runs sync.
        Use ``list_templates`` first to see available options.
        """
        return await run_script("python3", "scripts/init_template.py", template_name, cwd=paper_dir)

    @tool(catch=True)
    async def list_templates() -> str:
        """List all available conference templates."""
        return await run_script("python3", "scripts/init_template.py", "--list", cwd=paper_dir)

    @tool(catch=True)
    async def list_reviews() -> str:
        """List and summarize peer review records from the ``reviews/`` directory."""
        return await run_script("python3", "scripts/reviews.py", cwd=paper_dir, timeout=15)

    return [
        build_paper, sync_paper, validate_paper,
        search_citations, add_citation, paper_stats,
        generate_diff, switch_template, list_templates, list_reviews,
    ]
