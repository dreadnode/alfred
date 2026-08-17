#!/usr/bin/env python3
"""Report word counts, page count, figure/table counts for the paper.

Reads section files, strips LaTeX markup, and counts words per section.
Optionally reads the built PDF for page count.

Usage:
    python3 scripts/stats.py [--project-root PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

import yaml


def strip_latex(text: str) -> str:
    """Strip LaTeX markup from text for approximate word counting.

    Removes comments, non-prose environments (figures, tables, equations,
    code listings), math, and commands. Keeps text arguments of formatting
    commands like \\textbf.
    """
    # Remove comments
    text = re.sub(r"(?<!\\)%.*", "", text)
    # Remove non-prose environments (including starred variants)
    text = re.sub(
        r"\\begin\{((?:equation|align|lstlisting|verbatim|figure|table)\*?)\}.*?\\end\{\1\}",
        "",
        text,
        flags=re.DOTALL,
    )
    # Remove math (inline $...$ and display \[...\])
    text = re.sub(r"\$[^$]*\$", " MATH ", text)
    text = re.sub(r"\\\[.*?\\\]", " MATH ", text, flags=re.DOTALL)
    # Remove commands but keep their text arguments
    text = re.sub(
        r"\\(?:textbf|textit|emph|texttt|underline|textcolor\{[^}]*\})\{([^}]*)\}",
        r"\1",
        text,
    )
    # Remove remaining commands
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])*(\{[^}]*\})*", " ", text)
    # Remove braces
    text = re.sub(r"[{}]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def count_words(text: str) -> int:
    """Count words in LaTeX source after stripping markup."""
    stripped = strip_latex(text)
    if not stripped:
        return 0
    return len(stripped.split())


def count_pattern(text: str, pattern: str) -> int:
    """Count regex pattern occurrences in text."""
    return len(re.findall(pattern, text))


def get_page_count(project_root: str) -> int | None:
    """Get page count from the built PDF, or None if unavailable."""
    pdf_path = os.path.join(project_root, "build", "main.pdf")
    if not os.path.exists(pdf_path):
        return None

    # Try pdfinfo (most accurate)
    try:
        result = subprocess.run(
            ["pdfinfo", pdf_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.split("\n"):
            if line.startswith("Pages:"):
                return int(line.split(":")[1].strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    # Fallback: count /Type /Page objects in PDF binary
    try:
        with open(pdf_path, "rb") as f:
            content = f.read()
        pages = len(re.findall(rb"/Type\s*/Page[^s]", content))
        if pages > 0:
            return pages
    except Exception:
        pass

    return None


def stats(project_root: str, *, as_json: bool = False) -> int:
    """Compute and display paper statistics.

    Returns 0 on success, 1 on error.
    """
    manifest_path = os.path.join(project_root, "paper.yaml")
    if not os.path.exists(manifest_path):
        print("ERROR: paper.yaml not found", file=sys.stderr)
        return 1

    with open(manifest_path) as f:
        manifest: dict[str, Any] = yaml.safe_load(f) or {}

    sections: list[dict[str, str]] = manifest.get("sections", [])
    section_stats: list[dict[str, Any]] = []
    total_words = 0
    total_figures = 0
    total_tables = 0
    total_citations = 0
    total_equations = 0

    for s in sections:
        slug = s["slug"]
        title = s.get("title", slug)
        filepath = os.path.join(project_root, "section", f"{slug}.tex")

        if not os.path.exists(filepath):
            section_stats.append(
                {"slug": slug, "title": title, "words": 0, "exists": False}
            )
            continue

        with open(filepath) as f:
            content = f.read()

        words = count_words(content)
        figures = count_pattern(content, r"\\begin\{figure")
        tables = count_pattern(content, r"\\begin\{table")
        citations = count_pattern(content, r"\\cite[tp]?\{")
        equations = count_pattern(content, r"\\begin\{(equation|align)")

        total_words += words
        total_figures += figures
        total_tables += tables
        total_citations += citations
        total_equations += equations

        section_stats.append(
            {
                "slug": slug,
                "title": title,
                "words": words,
                "figures": figures,
                "tables": tables,
                "citations": citations,
                "equations": equations,
                "exists": True,
            }
        )

    pages = get_page_count(project_root)

    if as_json:
        print(
            json.dumps(
                {
                    "total_words": total_words,
                    "pages": pages,
                    "figures": total_figures,
                    "tables": total_tables,
                    "citations": total_citations,
                    "equations": total_equations,
                    "sections": section_stats,
                },
                indent=2,
            )
        )
    else:
        print("=== Paper Statistics ===\n")
        print(f"  {'Section':<30s} {'Words':>6s}")
        print(f"  {'-' * 30} {'-' * 6}")
        for s in section_stats:
            if not s["exists"]:
                print(f"  {s['title']:<30s} {'(missing)':>6s}")
            else:
                print(f"  {s['title']:<30s} {s['words']:>6d}")
        print(f"  {'-' * 30} {'-' * 6}")
        print(f"  {'Total':<30s} {total_words:>6d}")
        print()
        print(f"  Pages:     {pages if pages else '(build first)'}")
        print(f"  Figures:   {total_figures}")
        print(f"  Tables:    {total_tables}")
        print(f"  Citations: {total_citations}")
        print(f"  Equations: {total_equations}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper word count and statistics")
    parser.add_argument("--project-root", default=None, help="Project root directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    root = args.project_root or os.getcwd()
    if not os.path.isfile(os.path.join(root, "paper.yaml")):
        print(
            "ERROR: paper.yaml not found. Run from a paper directory or pass --project-root.",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(stats(root, as_json=args.json))


if __name__ == "__main__":
    main()
