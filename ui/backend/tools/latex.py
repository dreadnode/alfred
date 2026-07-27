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

    async def _do_build() -> str:
        """Shared build logic used by build_paper and build_paper_and_show."""
        try:
            return await run_script(
                "bash", "scripts/build.sh", cwd=paper_dir, timeout=120
            )
        except RuntimeError as exc:
            log_path = os.path.join(paper_dir, "build", "main.log")
            extra = ""
            if os.path.exists(log_path):
                with open(log_path) as f:
                    lines = f.readlines()
                errors = [
                    line.rstrip()
                    for line in lines
                    if line.startswith("!") or "Error" in line
                ]
                if errors:
                    extra = "\n\n--- Build Errors ---\n" + "\n".join(errors[:20])
            raise RuntimeError(f"{exc}{extra}") from exc

    @tool(catch=True)
    async def build_paper() -> str:
        """Build the LaTeX paper to PDF.

        Runs ``scripts/build.sh`` and returns the build output.
        If the build fails, appends relevant error lines from ``build/main.log``.
        """
        return await _do_build()

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
            "bash",
            "scripts/validate.sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=paper_dir,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "Validation timed out after 30 seconds."
        return stdout.decode(errors="replace")

    @tool(catch=True)
    async def search_citations(
        query: t.Annotated[str, "Search query for Semantic Scholar"],
    ) -> str:
        """Search for academic citations using Semantic Scholar."""
        return await run_script(
            "python3", "scripts/cite.py", "search", query, cwd=paper_dir
        )

    @tool(catch=True)
    async def add_citation(
        citation_id: t.Annotated[str, "Citation ID from search results to add"],
    ) -> str:
        """Add a citation to ``bibliography.bib`` by its ID."""
        return await run_script(
            "python3", "scripts/cite.py", "add", citation_id, cwd=paper_dir
        )

    @tool(catch=True)
    async def paper_stats() -> str:
        """Get paper statistics — word count, pages, figures, tables."""
        return await run_script(
            "python3", "scripts/stats.py", cwd=paper_dir, timeout=15
        )

    @tool(catch=True)
    async def generate_diff(
        revision: t.Annotated[
            str, "Git revision to diff against (e.g. HEAD, HEAD~3, commit hash)"
        ] = "HEAD",
    ) -> str:
        """Generate a track-changes PDF diffing current source against a git revision.

        Output is written to ``build/diff.pdf`` with additions in blue and
        deletions in red strikethrough. Requires ``latexdiff`` to be installed.
        """
        return await run_script(
            "python3", "scripts/diff.py", revision, cwd=paper_dir, timeout=120
        )

    @tool(catch=True)
    async def switch_template(
        template_name: t.Annotated[
            str, "Template name (e.g. neurips2024, ieee, acm, usenix, acl, article)"
        ],
    ) -> str:
        """Switch the paper to a different conference template.

        Copies template files, updates ``paper.yaml``, and runs sync.
        Use ``list_templates`` first to see available options.
        """
        return await run_script(
            "python3", "scripts/init_template.py", template_name, cwd=paper_dir
        )

    @tool(catch=True)
    async def list_templates() -> str:
        """List all available conference templates."""
        return await run_script(
            "python3", "scripts/init_template.py", "--list", cwd=paper_dir
        )

    @tool(catch=True)
    async def list_reviews() -> str:
        """List and summarize peer review records from the ``reviews/`` directory."""
        return await run_script(
            "python3", "scripts/reviews.py", cwd=paper_dir, timeout=15
        )

    async def _notify_viewer() -> None:
        """Push a pdf_updated event to all connected viewer clients."""
        import json
        import time as _time

        from .. import server as srv

        msg = json.dumps({"type": "pdf_updated", "timestamp": _time.time()})
        for ws in list(srv._pdf_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                srv._pdf_clients.discard(ws)

    def _resolve_pdf_path(path: str) -> str:
        """Expand and resolve a PDF path, raising on invalid input."""
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            expanded = os.path.join(paper_dir, expanded)
        expanded = os.path.abspath(expanded)
        if not os.path.isfile(expanded):
            raise FileNotFoundError(f"PDF not found: {path}")
        if not expanded.lower().endswith(".pdf"):
            raise ValueError(f"Not a PDF file: {path}")
        return expanded

    @tool(catch=True)
    async def show_pdf(
        path: t.Annotated[
            str,
            "Path to a PDF file to display (absolute, ~/relative, or relative to paper dir)",
        ],
    ) -> str:
        """Display a PDF in the user's viewer pane (right side of the web UI).

        This ONLY changes what the user sees — it does NOT read the PDF text.
        To also read the content, call ``read_pdf`` separately.

        The viewer stays on this PDF until you call ``show_project_pdf``
        or ``build_paper_and_show``.
        """
        from .. import server as srv

        resolved = _resolve_pdf_path(path)
        srv._custom_pdf = resolved
        await _notify_viewer()
        return f"Viewer now showing: {resolved}"

    @tool(catch=True)
    async def show_project_pdf() -> str:
        """Switch the viewer back to the project's built PDF (build/main.pdf).

        Call this after you're done working with an external PDF and want
        the user to see their own paper again.
        """
        from .. import server as srv

        srv._custom_pdf = None
        await _notify_viewer()
        return "Viewer now showing: build/main.pdf"

    @tool(catch=True)
    async def read_pdf(
        path: t.Annotated[
            str, "Path to a PDF file (absolute, ~/relative, or relative to paper dir)"
        ],
        pages: t.Annotated[
            str, "Page range to extract, e.g. '1-5' or '3'. Omit for all pages."
        ] = "",
    ) -> str:
        """Extract text content from a PDF file and return it.

        This ONLY reads the text — it does NOT display the PDF in the viewer.
        To also show it to the user, call ``show_pdf`` separately.

        Typical workflow for an external paper:
          1. show_pdf(path)   — user sees it in the viewer
          2. read_pdf(path)   — you get the text to work with
        """
        resolved = _resolve_pdf_path(path)

        cmd = ["pdftotext"]
        if pages:
            if "-" in pages:
                first, last = pages.split("-", 1)
                cmd.extend(["-f", first.strip(), "-l", last.strip()])
            else:
                cmd.extend(["-f", pages.strip(), "-l", pages.strip()])
        cmd.extend([resolved, "-"])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"pdftotext failed: {err}")

        text = stdout.decode("utf-8", errors="replace")
        if not text.strip():
            return "No text extracted (PDF may be image-only or empty)."
        return text

    @tool(catch=True)
    async def build_paper_and_show() -> str:
        """Build the paper AND switch the viewer to show the result.

        Use this instead of ``build_paper`` when an external PDF is loaded
        in the viewer and you want the user to see the build output.
        It resets the viewer to build/main.pdf, runs the build, and
        notifies the viewer to reload.

        If no external PDF is loaded, ``build_paper`` is sufficient.
        """
        from .. import server as srv

        srv._custom_pdf = None
        result = await _do_build()
        await _notify_viewer()
        return result

    return [
        build_paper,
        build_paper_and_show,
        sync_paper,
        validate_paper,
        search_citations,
        add_citation,
        paper_stats,
        generate_diff,
        switch_template,
        list_templates,
        list_reviews,
        show_pdf,
        show_project_pdf,
        read_pdf,
    ]
