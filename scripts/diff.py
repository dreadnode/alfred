#!/usr/bin/env python3
"""Generate a track-changes PDF by diffing against a git commit.

Compares current LaTeX source against a previous git revision using
latexdiff, then compiles the result into build/diff.pdf with additions
in blue and deletions in red strikethrough.

Requires: latexdiff (install via `sudo tlmgr install latexdiff` or
`brew install latexdiff`)

Usage:
    python3 scripts/diff.py              # diff against last commit
    python3 scripts/diff.py HEAD~3       # diff against 3 commits ago
    python3 scripts/diff.py abc123       # diff against specific commit
    python3 scripts/diff.py main         # diff against a branch
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _check_tool(name: str) -> bool:
    """Check if a command-line tool is available."""
    return shutil.which(name) is not None


def _git_show_file(project_root: str, rev: str, filepath: str) -> str | None:
    """Get the contents of a file at a given git revision."""
    rel_path = os.path.relpath(filepath, project_root)
    result = _run(["git", "-C", project_root, "show", f"{rev}:{rel_path}"])
    if result.returncode != 0:
        return None
    return result.stdout


def _get_section_files(project_root: str) -> list[str]:
    """Get list of section .tex files referenced in main.tex."""
    main_tex = os.path.join(project_root, "main.tex")
    files = []
    if os.path.exists(main_tex):
        with open(main_tex) as f:
            for line in f:
                m = re.match(r"\\input\{section/([^}]+)\}", line.strip())
                if m:
                    files.append(os.path.join(project_root, "section", f"{m.group(1)}.tex"))
    return files


def diff(project_root: str, rev: str = "HEAD") -> int:
    """Generate a diff PDF comparing current source against a git revision.

    Returns 0 on success, 1 on error.
    """
    # Check prerequisites
    if not _check_tool("latexdiff"):
        print("ERROR: latexdiff not found.", file=sys.stderr)
        print("Install with: sudo tlmgr install latexdiff", file=sys.stderr)
        print("         or: brew install latexdiff", file=sys.stderr)
        return 1

    if not _check_tool("latexmk"):
        print("ERROR: latexmk not found.", file=sys.stderr)
        return 1

    # Verify the revision exists
    result = _run(["git", "-C", project_root, "rev-parse", "--verify", rev])
    if result.returncode != 0:
        print(f"ERROR: git revision '{rev}' not found.", file=sys.stderr)
        return 1

    rev_short = _run(["git", "-C", project_root, "rev-parse", "--short", rev]).stdout.strip()
    print(f"Diffing against: {rev} ({rev_short})")

    main_tex = os.path.join(project_root, "main.tex")
    if not os.path.exists(main_tex):
        print("ERROR: main.tex not found.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="agentic-latex-diff-") as tmpdir:
        old_dir = os.path.join(tmpdir, "old")
        diff_dir = os.path.join(tmpdir, "diff")
        os.makedirs(old_dir)
        os.makedirs(diff_dir)

        # Step 1: Extract old main.tex
        old_main = _git_show_file(project_root, rev, main_tex)
        if old_main is None:
            print(f"ERROR: main.tex not found at revision {rev}.", file=sys.stderr)
            return 1

        old_main_path = os.path.join(old_dir, "main.tex")
        with open(old_main_path, "w") as f:
            f.write(old_main)

        # Step 2: Extract old section files
        old_section_dir = os.path.join(old_dir, "section")
        os.makedirs(old_section_dir, exist_ok=True)

        section_files = _get_section_files(project_root)
        for sec_path in section_files:
            old_content = _git_show_file(project_root, rev, sec_path)
            basename = os.path.basename(sec_path)
            old_sec_path = os.path.join(old_section_dir, basename)
            if old_content is not None:
                with open(old_sec_path, "w") as f:
                    f.write(old_content)
            else:
                # File didn't exist in old revision — create empty
                with open(old_sec_path, "w") as f:
                    f.write("")

        # Step 3: Run latexdiff on main.tex (flatten to handle \input)
        print("  Running latexdiff...")
        diff_main_path = os.path.join(diff_dir, "main.tex")
        result = _run([
            "latexdiff",
            "--flatten",
            old_main_path,
            main_tex,
        ])

        if result.returncode != 0:
            print(f"  latexdiff error: {result.stderr}", file=sys.stderr)
            return 1

        with open(diff_main_path, "w") as f:
            f.write(result.stdout)

        # Step 4: Copy supporting files needed for compilation
        for item in ["bibliography.bib", ".latexmkrc", "styles", "figures", "data"]:
            src = os.path.join(project_root, item)
            dst = os.path.join(diff_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)

        # Copy any .cls/.sty files from project root (template files)
        for f_name in os.listdir(project_root):
            if f_name.endswith((".cls", ".sty", ".bst")):
                shutil.copy2(
                    os.path.join(project_root, f_name),
                    os.path.join(diff_dir, f_name),
                )

        # Step 5: Compile the diff
        print("  Compiling diff PDF...")
        build_dir = os.path.join(diff_dir, "build")
        os.makedirs(build_dir, exist_ok=True)

        result = _run(
            ["latexmk", "-pdf", "-interaction=nonstopmode", "-outdir=build", "main.tex"],
            cwd=diff_dir,
            timeout=120,
        )

        diff_pdf = os.path.join(build_dir, "main.pdf")
        if not os.path.exists(diff_pdf):
            print("  Compilation failed. latexmk output:", file=sys.stderr)
            # Show just the error lines
            for line in result.stdout.split("\n"):
                if line.startswith("!"):
                    print(f"    {line}", file=sys.stderr)
            return 1

        # Step 6: Copy result to project build directory
        out_dir = os.path.join(project_root, "build")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "diff.pdf")
        shutil.copy2(diff_pdf, out_path)

        print(f"\n  Output: build/diff.pdf")
        print(f"  Compared against: {rev} ({rev_short})")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a track-changes PDF by diffing against a git commit",
    )
    parser.add_argument(
        "revision", nargs="?", default="HEAD",
        help="Git revision to diff against (default: HEAD)",
    )
    parser.add_argument("--project-root", default=None, help="Project root directory")
    args = parser.parse_args()

    root = args.project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.exit(diff(root, rev=args.revision))


if __name__ == "__main__":
    main()
