#!/usr/bin/env python3
"""Sync paper.yaml → main.tex managed regions.

Reads the paper manifest and updates marker-delimited regions in main.tex.
On first run, inserts markers around existing content (migration).
Template-aware: renders author-block and bibliography based on active template.

Usage:
    python3 scripts/sync.py [--dry-run] [--project-root PATH]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from typing import Any

import yaml

# Templates live in the repo, not in per-paper directories.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MARKER_BEGIN = "% BEGIN SYNC: {}"
MARKER_END = "% END SYNC: {}"
REQUIRED_REGIONS = ["bibliography", "metadata", "macros", "styles", "sections"]
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _validate_name(value: Any, kind: str) -> str:
    """Return a safe single path component or raise ``ValueError``."""
    if not isinstance(value, str) or not _SAFE_NAME_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {kind} {value!r}; use only letters, numbers, '_' and '-'"
        )
    return value


def _atomic_write_text(path: str, content: str) -> None:
    """Atomically replace a UTF-8 text file in its existing directory."""
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, os.stat(path).st_mode & 0o777)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_yaml(path: str) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def has_markers(tex: str, region: str) -> bool:
    """Check whether both BEGIN and END markers exist for a region."""
    return MARKER_BEGIN.format(region) in tex and MARKER_END.format(region) in tex


def replace_region(tex: str, region: str, content: str) -> str:
    """Replace the content between a region's sync markers."""
    begin = MARKER_BEGIN.format(region)
    end = MARKER_END.format(region)
    pattern = re.compile(
        re.escape(begin) + r"\n.*?" + re.escape(end),
        re.DOTALL,
    )
    replacement = begin + "\n" + content + end
    return pattern.sub(lambda _: replacement, tex)


def get_region_content(tex: str, region: str) -> str | None:
    """Extract the content between a region's sync markers."""
    begin = MARKER_BEGIN.format(region)
    end = MARKER_END.format(region)
    pattern = re.compile(
        re.escape(begin) + r"\n(.*?)" + re.escape(end),
        re.DOTALL,
    )
    match = pattern.search(tex)
    return match.group(1) if match else None


def load_template_config(template_name: str) -> dict[str, Any]:
    """Load configuration for an installed template."""
    template_name = _validate_name(template_name, "template name")
    path = os.path.join(_REPO_ROOT, "templates", template_name, "template.yaml")
    if not os.path.isfile(path):
        raise ValueError(f"Unknown template: {template_name}")
    return load_yaml(path)


# --- Migration: insert markers on first run ---


def insert_markers(tex: str) -> tuple[str, list[str]]:
    """Insert sync markers around existing content in a fresh main.tex.

    Detects known LaTeX patterns (biblatex, metadata commands, etc.) and
    wraps them with BEGIN/END SYNC markers. Only runs when markers are
    absent — safe to call on already-migrated files.

    Returns the (possibly modified) tex string and a list of change descriptions.
    """
    changes: list[str] = []

    # Bibliography region
    if not has_markers(tex, "bibliography"):
        pattern = re.compile(
            r"(\\usepackage\[.*?\]\{biblatex\}\n\\addbibresource\{.*?\})",
        )
        match = pattern.search(tex)
        if not match:
            pattern = re.compile(r"(\\bibliographystyle\{.*?\})")
            match = pattern.search(tex)
        if match:
            old = match.group(0)
            tex = tex.replace(
                old,
                MARKER_BEGIN.format("bibliography")
                + "\n"
                + old
                + "\n"
                + MARKER_END.format("bibliography"),
            )
            changes.append("Inserted markers: bibliography")

    # Metadata region
    if not has_markers(tex, "metadata"):
        pattern = re.compile(
            r"(% Paper metadata\n"
            r"\\newcommand\{\\papertitle\}\{.*\}\n"
            r"\\newcommand\{\\paperauthors\}\{.*\})",
        )
        match = pattern.search(tex)
        if match:
            old = match.group(0)
            tex = tex.replace(
                old,
                MARKER_BEGIN.format("metadata")
                + "\n"
                + old
                + "\n"
                + MARKER_END.format("metadata"),
            )
            changes.append("Inserted markers: metadata")

    # Macros region — inserted after the \todo convenience macro
    if not has_markers(tex, "macros"):
        pattern = re.compile(r"\\newcommand\{\\todo\}.*")
        match = pattern.search(tex)
        if match:
            end_of_line = tex.index("\n", match.start()) + 1
            rest = tex[end_of_line:]
            skip_lines = 0
            for line in rest.split("\n"):
                if line.strip() == "":
                    skip_lines += len(line) + 1
                else:
                    break
            insert_pos = end_of_line + skip_lines
            marker_block = (
                "\n"
                + MARKER_BEGIN.format("macros")
                + "\n"
                + MARKER_END.format("macros")
                + "\n"
            )
            tex = tex[:insert_pos] + marker_block + tex[insert_pos:]
            changes.append("Inserted markers: macros")

    # Styles region
    if not has_markers(tex, "styles"):
        pattern = re.compile(
            r"(% \\usepackage\{styles/.*\}.*\n)+"
            r"|"
            r"(\\usepackage\{styles/.*\}.*\n)+",
        )
        match = pattern.search(tex)
        if match:
            old = match.group(0).rstrip("\n")
            tex = tex.replace(
                old,
                MARKER_BEGIN.format("styles")
                + "\n"
                + old
                + "\n"
                + MARKER_END.format("styles"),
            )
            changes.append("Inserted markers: styles")

    # Sections region
    if not has_markers(tex, "sections"):
        pattern = re.compile(r"(% --- Sections ---\n)?(\\input\{section/.*\}\n)+")
        match = pattern.search(tex)
        if match:
            old = match.group(0).rstrip("\n")
            content = "\n".join(
                line for line in old.split("\n") if line.startswith("\\input{")
            )
            tex = tex.replace(
                old,
                MARKER_BEGIN.format("sections")
                + "\n"
                + content
                + "\n"
                + MARKER_END.format("sections"),
            )
            changes.append("Inserted markers: sections")

    return tex, changes


# --- Render functions ---


def render_metadata(manifest: dict[str, Any]) -> str:
    """Render \\papertitle and \\paperauthors newcommands."""
    title = manifest.get("title", "Paper Title")
    authors: list[dict[str, str]] = manifest.get("authors", [])
    author_names = ", ".join(a.get("name", "") for a in authors)
    lines = [
        "% Paper metadata",
        f"\\newcommand{{\\papertitle}}{{{title}}}",
        f"\\newcommand{{\\paperauthors}}{{{author_names}}}",
    ]
    return "\n".join(lines) + "\n"


def render_macros(manifest: dict[str, Any]) -> str:
    """Render custom \\newcommand entries from paper.yaml macros dict."""
    macros: dict[str, str] = manifest.get("macros", {})
    if not macros:
        return ""
    lines = []
    for key, value in macros.items():
        if key in ("papertitle", "paperauthors"):
            continue
        lines.append(f"\\newcommand{{\\{key}}}{{{value}}}")
    return "\n".join(lines) + "\n" if lines else ""


def render_styles(manifest: dict[str, Any]) -> str:
    """Render \\usepackage lines for optional style packages."""
    styles: list[str] = manifest.get("styles", [])
    if not styles:
        return ""
    lines = [
        f"\\usepackage{{styles/{_validate_name(name, 'style name')}}}"
        for name in styles
    ]
    return "\n".join(lines) + "\n"


def ensure_style_files(
    manifest: dict[str, Any], root: str, *, dry_run: bool = False
) -> list[str]:
    """Copy missing selected style packages into the paper directory."""
    changes: list[str] = []
    styles: list[str] = manifest.get("styles", [])
    for raw_name in styles:
        name = _validate_name(raw_name, "style name")
        source = os.path.join(_REPO_ROOT, "styles", f"{name}.sty")
        if not os.path.isfile(source):
            raise ValueError(f"Unknown style package: {name}")
        destination = os.path.join(root, "styles", f"{name}.sty")
        if os.path.exists(destination):
            continue
        if dry_run:
            changes.append(f"Would copy: styles/{name}.sty")
        else:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            changes.append(f"Copied: styles/{name}.sty")
    return changes


def render_bibliography(
    manifest: dict[str, Any],
    bib_system: str = "biblatex",
    template_config: dict[str, Any] | None = None,
) -> str:
    """Render bibliography configuration for a template's bibliography system."""
    bib = manifest.get("bibliography", {})
    bib_file = bib.get("file", "bibliography.bib")
    tc = template_config or {}

    if bib_system == "builtin":
        return ""
    elif bib_system == "natbib":
        style = tc.get("natbib_style", bib.get("natbib_style", "unsrtnat"))
        return f"\\bibliographystyle{{{style}}}\n"
    elif bib_system == "bibtex":
        style = tc.get("bibtex_style", bib.get("bibtex_style", "plain"))
        return f"\\bibliographystyle{{{style}}}\n"
    else:  # biblatex
        backend = bib.get("backend", "biber")
        style = bib.get("style", "numeric")
        sorting = bib.get("sorting", "nyt")
        maxbibnames = bib.get("maxbibnames", 99)
        lines = [
            f"\\usepackage[backend={backend},style={style},sorting={sorting},maxbibnames={maxbibnames}]{{biblatex}}",
            f"\\addbibresource{{{bib_file}}}",
        ]
        return "\n".join(lines) + "\n"


def render_sections(manifest: dict[str, Any]) -> str:
    """Render \\input lines for each section in order."""
    sections: list[dict[str, str]] = manifest.get("sections", [])
    lines = [
        f"\\input{{section/{_validate_name(s['slug'], 'section slug')}}}"
        for s in sections
    ]
    return "\n".join(lines) + "\n"


def render_author_block(
    manifest: dict[str, Any], author_format: str = "article"
) -> str:
    """Render the title/author/maketitle block for a given conference format.

    Each format produces conference-specific LaTeX for author names,
    affiliations, and emails.
    """
    title = manifest.get("title", "Paper Title")
    authors: list[dict[str, str]] = manifest.get("authors", []) or [
        {"name": "Anonymous Author"}
    ]

    if author_format == "neurips":
        author_parts = []
        for a in authors:
            parts = [a.get("name", "")]
            if a.get("affiliation"):
                parts.append(a["affiliation"])
            if a.get("email"):
                parts.append(f"\\texttt{{{a['email']}}}")
            author_parts.append(" \\\\\n  ".join(parts))
        author_str = " \\And\n  ".join(author_parts)
        return f"\\title{{{title}}}\n\\author{{\n  {author_str}\n}}\n\\maketitle\n"

    elif author_format == "ieee":
        author_blocks = []
        for a in authors:
            block = f"\\IEEEauthorblockN{{{a.get('name', '')}}}"
            aff_parts = []
            if a.get("affiliation"):
                aff_parts.append(a["affiliation"])
            if a.get("email"):
                aff_parts.append(a["email"])
            if aff_parts:
                block += "\n\\IEEEauthorblockA{" + "\\\\".join(aff_parts) + "}"
            author_blocks.append(block)
        author_str = "\n\\and\n".join(author_blocks)
        return f"\\title{{{title}}}\n\\author{{{author_str}}}\n\\maketitle\n"

    elif author_format == "ndss":
        author_blocks = []
        for a in authors:
            block = f"\\IEEEauthorblockN{{{a.get('name', '')}}}"
            details = [a.get("affiliation", ""), a.get("email", "")]
            details = [detail for detail in details if detail]
            if details:
                block += "\n\\IEEEauthorblockA{" + "\\\\".join(details) + "}"
            author_blocks.append(block)
        camera_ready_authors = "\n\\and\n".join(author_blocks)
        return (
            f"\\title{{{title}}}\n"
            "\\ifndssanonymous\n"
            "  \\author{\\IEEEauthorblockN{Anonymous Submission}}\n"
            "\\else\n"
            f"  \\author{{{camera_ready_authors}}}\n"
            "\\fi\n"
            "\\maketitle\n"
        )

    elif author_format == "acm":
        lines = [f"\\title{{{title}}}"]
        for a in authors:
            lines.append(f"\\author{{{a.get('name', '')}}}")
            if a.get("affiliation"):
                lines.append(f"\\affiliation{{\\institution{{{a['affiliation']}}}}}")
            if a.get("email"):
                lines.append(f"\\email{{{a['email']}}}")
        lines.append("\\maketitle")
        return "\n".join(lines) + "\n"

    elif author_format == "usenix":
        author_parts = []
        for a in authors:
            name = a.get("name", "")
            parts = [f"{{\\rm {name}}}"]
            if a.get("affiliation"):
                parts.append(a["affiliation"])
            author_parts.append("\\\\".join(parts))
        author_str = " \\and ".join(author_parts)
        return f"\\title{{{title}}}\n\\author{{{author_str}}}\n\\maketitle\n"

    elif author_format == "acl":
        author_parts = []
        for a in authors:
            parts = [a.get("name", "")]
            if a.get("affiliation"):
                parts.append(a["affiliation"])
            if a.get("email"):
                parts.append(f"\\texttt{{{a['email']}}}")
            author_parts.append(" \\\\ ".join(parts))
        author_str = " \\And ".join(author_parts)
        return f"\\title{{{title}}}\n\\author{{{author_str}}}\n\\maketitle\n"

    elif author_format == "cvpr":
        author_parts = []
        for a in authors:
            parts = [a.get("name", "")]
            if a.get("affiliation"):
                parts.append(a["affiliation"])
            if a.get("email"):
                parts.append(f"{{\\tt\\small {a['email']}}}")
            author_parts.append(" \\\\\n".join(parts))
        author_str = "\n\\and\n".join(author_parts)
        return f"\\title{{{title}}}\n\\author{{{author_str}}}\n\\maketitle\n"

    elif author_format == "aaai":
        names = []
        affiliations = []
        for index, a in enumerate(authors, start=1):
            names.append(f"{a.get('name', '')}\\textsuperscript{{\\rm {index}}}")
            details = []
            if a.get("affiliation"):
                details.append(a["affiliation"])
            if a.get("email"):
                details.append(f"\\texttt{{{a['email']}}}")
            affiliations.append(
                f"\\textsuperscript{{\\rm {index}}}" + " \\\\ ".join(details)
            )
        affiliation_block = " \\\\ ".join(affiliations)
        return (
            f"\\title{{{title}}}\n"
            f"\\author{{{', '.join(names)}}}\n"
            f"\\affiliations{{{affiliation_block}}}\n"
            "\\maketitle\n"
        )

    elif author_format == "lncs":
        names = [
            f"{a.get('name', '')}\\inst{{{index}}}"
            for index, a in enumerate(authors, start=1)
        ]
        institutes = []
        for a in authors:
            details = [a.get("affiliation", "")]
            if a.get("email"):
                details.append(f"\\email{{{a['email']}}}")
            institutes.append(" \\\\ ".join(part for part in details if part))
        if len(authors) > 2:
            running_author = f"{authors[0].get('name', '')} et al."
        else:
            running_author = " and ".join(a.get("name", "") for a in authors)
        author_block = " \\and ".join(names)
        institute_block = " \\and ".join(institutes)
        return (
            f"\\title{{{title}}}\n"
            f"\\author{{{author_block}}}\n"
            f"\\authorrunning{{{running_author}}}\n"
            f"\\institute{{{institute_block}}}\n"
            "\\maketitle\n"
        )

    elif author_format == "icml":
        lines = [
            "\\twocolumn[",
            f"  \\icmltitle{{{title}}}",
            "  \\begin{icmlauthorlist}",
        ]
        for index, a in enumerate(authors):
            lines.append(f"    \\icmlauthor{{{a.get('name', '')}}}{{aff{index}}}")
        lines.append("  \\end{icmlauthorlist}")
        for index, a in enumerate(authors):
            lines.append(
                f"  \\icmlaffiliation{{aff{index}}}{{{a.get('affiliation', '')}}}"
            )
        for a in authors:
            if a.get("email"):
                lines.append(
                    f"  \\icmlcorrespondingauthor{{{a.get('name', '')}}}"
                    f"{{{a['email']}}}"
                )
        lines.extend(["  \\vskip 0.3in", "]", "\\printAffiliationsAndNotice{}"])
        return "\n".join(lines) + "\n"

    else:  # article (default)
        return (
            "\\title{\\papertitle}\n"
            "\\author{\\paperauthors}\n"
            "\\date{\\today}\n"
            "\\maketitle\n"
        )


def ensure_section_files(
    manifest: dict[str, Any], root: str, *, dry_run: bool = False
) -> list[str]:
    """Create missing section .tex files referenced in paper.yaml.

    Returns a list of change descriptions.
    """
    changes: list[str] = []
    sections: list[dict[str, str]] = manifest.get("sections", [])
    for s in sections:
        slug = _validate_name(s["slug"], "section slug")
        title = s.get("title", slug)
        filepath = os.path.join(root, "section", f"{slug}.tex")
        if not os.path.exists(filepath):
            if dry_run:
                changes.append(f"Would create: section/{slug}.tex")
            else:
                if slug.endswith("_abstract") or slug == "00_abstract":
                    content = (
                        "\\begin{abstract}\n"
                        "\\tbd{Write your abstract here.}\n"
                        "\\end{abstract}\n"
                    )
                else:
                    content = (
                        f"\\section{{{title}}}\n"
                        f"\\label{{sec:{slug}}}\n"
                        "\n"
                        f"\\tbd{{Write content for {title}.}}\n"
                    )
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, "w") as f:
                    f.write(content)
                changes.append(f"Created: section/{slug}.tex")
    return changes


def sync(project_root: str, *, dry_run: bool = False) -> int:
    """Main sync: read paper.yaml and update managed regions in main.tex.

    Returns 0 on success, 1 on error.
    """
    manifest_path = os.path.join(project_root, "paper.yaml")
    tex_path = os.path.join(project_root, "main.tex")
    all_changes: list[str] = []

    if not os.path.exists(manifest_path):
        print("ERROR: paper.yaml not found", file=sys.stderr)
        return 1
    if not os.path.exists(tex_path):
        print("ERROR: main.tex not found", file=sys.stderr)
        return 1

    manifest = load_yaml(manifest_path)
    with open(tex_path) as f:
        tex = f.read()

    original_tex = tex

    # Load template config
    template_name = manifest.get("template", "article")
    try:
        template_config = load_template_config(template_name)
        render_sections(manifest)
        render_styles(manifest)
        # Validate selected packages before creating section/style files.
        pending_style_changes = ensure_style_files(manifest, project_root, dry_run=True)
    except (KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    author_format = template_config.get("author_format", "article")
    bib_system = template_config.get("bibliography_system", "biblatex")

    # Step 1: Insert markers if missing (migration)
    tex, migration_changes = insert_markers(tex)
    all_changes.extend(migration_changes)

    # Step 2: Verify required markers present
    missing = [r for r in REQUIRED_REGIONS if not has_markers(tex, r)]
    if missing:
        print(
            f"ERROR: Could not find/insert markers for: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    # Step 3: Render and replace each region
    renders: dict[str, str] = {
        "metadata": render_metadata(manifest),
        "macros": render_macros(manifest),
        "styles": render_styles(manifest),
        "bibliography": render_bibliography(manifest, bib_system, template_config),
        "sections": render_sections(manifest),
    }

    if has_markers(tex, "author-block"):
        renders["author-block"] = render_author_block(manifest, author_format)

    for region, new_content in renders.items():
        old_content = get_region_content(tex, region)
        if old_content != new_content:
            tex = replace_region(tex, region, new_content)
            all_changes.append(f"Updated region: {region}")

    # Step 4: Ensure section files exist
    file_changes = ensure_section_files(manifest, project_root, dry_run=dry_run)
    all_changes.extend(file_changes)
    style_changes = (
        pending_style_changes
        if dry_run
        else ensure_style_files(manifest, project_root, dry_run=False)
    )
    all_changes.extend(style_changes)

    # Step 5: Write if changed
    if tex != original_tex:
        if dry_run:
            all_changes.append("Would write main.tex (use without --dry-run to apply)")
        else:
            _atomic_write_text(tex_path, tex)

    # Report
    if all_changes:
        for change in all_changes:
            prefix = "[dry-run] " if dry_run else ""
            print(f"  {prefix}{change}")
    else:
        print("  No changes needed.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync paper.yaml → main.tex")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )
    parser.add_argument("--project-root", default=None, help="Project root directory")
    args = parser.parse_args()

    root = args.project_root or os.getcwd()
    if not os.path.isfile(os.path.join(root, "paper.yaml")):
        print(
            "ERROR: paper.yaml not found. Run from a paper directory or pass --project-root.",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(sync(root, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
