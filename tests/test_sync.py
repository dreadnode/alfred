"""Tests for scripts/sync.py."""

from __future__ import annotations

from sync import (
    ensure_section_files,
    get_region_content,
    has_markers,
    insert_markers,
    render_author_block,
    render_bibliography,
    render_macros,
    render_metadata,
    render_sections,
    render_styles,
    replace_region,
    sync,
)

# ---------------------------------------------------------------------------
# Marker detection and region manipulation
# ---------------------------------------------------------------------------

SAMPLE_TEX = (
    "preamble\n"
    "% BEGIN SYNC: test\n"
    "old content\n"
    "% END SYNC: test\n"
    "postamble\n"
)


class TestMarkers:
    def test_has_markers_present(self):
        assert has_markers(SAMPLE_TEX, "test") is True

    def test_has_markers_absent(self):
        assert has_markers(SAMPLE_TEX, "missing") is False

    def test_replace_region(self):
        result = replace_region(SAMPLE_TEX, "test", "new content\n")
        assert "new content" in result
        assert "old content" not in result
        assert "preamble" in result
        assert "postamble" in result
        assert "% BEGIN SYNC: test" in result
        assert "% END SYNC: test" in result

    def test_get_region_content(self):
        assert get_region_content(SAMPLE_TEX, "test") == "old content\n"

    def test_get_region_content_missing(self):
        assert get_region_content(SAMPLE_TEX, "missing") is None

    def test_replace_with_backslashes(self):
        """Ensure LaTeX commands in content don't break regex replacement."""
        result = replace_region(SAMPLE_TEX, "test", "\\usepackage{amsmath}\n")
        assert "\\usepackage{amsmath}" in result


# ---------------------------------------------------------------------------
# Migration: insert_markers
# ---------------------------------------------------------------------------

FRESH_TEX = (
    "\\documentclass{article}\n"
    "\\usepackage[backend=biber,style=numeric]{biblatex}\n"
    "\\addbibresource{bibliography.bib}\n"
    "% Paper metadata\n"
    "\\newcommand{\\papertitle}{My Title}\n"
    "\\newcommand{\\paperauthors}{Author A}\n"
    "\\newcommand{\\tbd}[1]{#1}\n"
    "\\newcommand{\\note}[1]{#1}\n"
    "\\newcommand{\\todo}[1]{#1}\n"
    "\n"
    "\\input{section/00_abstract}\n"
    "\\input{section/01_intro}\n"
)


class TestInsertMarkers:
    def test_inserts_all_detected_markers(self):
        result, changes = insert_markers(FRESH_TEX)
        assert has_markers(result, "bibliography")
        assert has_markers(result, "metadata")
        assert has_markers(result, "sections")
        assert len(changes) >= 3

    def test_preserves_content(self):
        result, _ = insert_markers(FRESH_TEX)
        assert "\\documentclass{article}" in result
        assert "\\addbibresource{bibliography.bib}" in result

    def test_idempotent(self):
        first, _ = insert_markers(FRESH_TEX)
        second, changes = insert_markers(first)
        assert second == first
        assert changes == []

    def test_handles_natbib_style(self):
        tex = "\\bibliographystyle{unsrtnat}\n\\begin{document}\n"
        result, _ = insert_markers(tex)
        assert has_markers(result, "bibliography")


# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------

MANIFEST = {
    "title": "Test Paper",
    "authors": [
        {"name": "Alice Smith", "affiliation": "MIT", "email": "alice@mit.edu"},
        {"name": "Bob Jones", "affiliation": "Stanford", "email": "bob@stanford.edu"},
    ],
    "sections": [
        {"slug": "00_abstract", "title": "Abstract"},
        {"slug": "01_introduction", "title": "Introduction"},
    ],
    "macros": {"NumModels": "5", "DatasetSize": "10{,}000"},
    "styles": ["messageboxes", "codeblocks"],
    "bibliography": {
        "backend": "biber",
        "style": "numeric",
        "sorting": "nyt",
        "maxbibnames": 99,
        "file": "refs.bib",
    },
}


class TestRenderMetadata:
    def test_renders_title_and_authors(self):
        result = render_metadata(MANIFEST)
        assert "\\newcommand{\\papertitle}{Test Paper}" in result
        assert "\\newcommand{\\paperauthors}{Alice Smith, Bob Jones}" in result


class TestRenderMacros:
    def test_renders_all_macros(self):
        result = render_macros(MANIFEST)
        assert "\\newcommand{\\NumModels}{5}" in result
        assert "\\newcommand{\\DatasetSize}{10{,}000}" in result

    def test_skips_reserved_keys(self):
        m = {**MANIFEST, "macros": {"papertitle": "x", "NumModels": "5"}}
        result = render_macros(m)
        assert "papertitle" not in result
        assert "NumModels" in result

    def test_empty_or_missing_macros(self):
        assert render_macros({"macros": {}}) == ""
        assert render_macros({}) == ""


class TestRenderStyles:
    def test_renders_packages(self):
        result = render_styles(MANIFEST)
        assert "\\usepackage{styles/messageboxes}" in result
        assert "\\usepackage{styles/codeblocks}" in result

    def test_empty_styles(self):
        assert render_styles({"styles": []}) == ""


class TestRenderBibliography:
    def test_biblatex(self):
        result = render_bibliography(MANIFEST)
        assert "\\usepackage[backend=biber" in result
        assert "\\addbibresource{refs.bib}" in result

    def test_natbib_default_style(self):
        result = render_bibliography(MANIFEST, bib_system="natbib")
        assert "\\bibliographystyle{unsrtnat}" in result
        assert "addbibresource" not in result

    def test_natbib_template_override(self):
        tc = {"natbib_style": "acl_natbib"}
        result = render_bibliography(MANIFEST, bib_system="natbib", template_config=tc)
        assert "\\bibliographystyle{acl_natbib}" in result

    def test_bibtex(self):
        result = render_bibliography(MANIFEST, bib_system="bibtex")
        assert "\\bibliographystyle{plain}" in result


class TestRenderSections:
    def test_renders_inputs_in_order(self):
        result = render_sections(MANIFEST)
        lines = result.strip().split("\n")
        assert lines[0] == "\\input{section/00_abstract}"
        assert lines[1] == "\\input{section/01_introduction}"


# ---------------------------------------------------------------------------
# Author block rendering per template
# ---------------------------------------------------------------------------

class TestRenderAuthorBlock:
    def test_article_uses_macros_not_literal_names(self):
        result = render_author_block(MANIFEST, "article")
        assert "\\papertitle" in result
        assert "\\paperauthors" in result
        assert "\\date{\\today}" in result
        assert "Alice Smith" not in result  # article uses macros, not literals

    def test_neurips_format(self):
        result = render_author_block(MANIFEST, "neurips")
        assert "\\And" in result
        assert "Alice Smith" in result
        assert "MIT" in result
        assert "\\texttt{alice@mit.edu}" in result

    def test_ieee_format(self):
        result = render_author_block(MANIFEST, "ieee")
        assert "\\IEEEauthorblockN{Alice Smith}" in result
        assert "\\IEEEauthorblockA{" in result

    def test_acm_format(self):
        result = render_author_block(MANIFEST, "acm")
        assert "\\author{Alice Smith}" in result
        assert "\\affiliation{\\institution{MIT}}" in result
        assert "\\email{alice@mit.edu}" in result

    def test_usenix_format(self):
        result = render_author_block(MANIFEST, "usenix")
        assert "{\\rm Alice Smith}" in result

    def test_acl_format(self):
        result = render_author_block(MANIFEST, "acl")
        assert "\\And" in result
        assert "Alice Smith" in result

    def test_all_formats_include_maketitle(self):
        for fmt in ["article", "neurips", "ieee", "acm", "usenix", "acl"]:
            result = render_author_block(MANIFEST, fmt)
            assert "\\maketitle" in result, f"{fmt} missing \\maketitle"


# ---------------------------------------------------------------------------
# Section file creation
# ---------------------------------------------------------------------------

class TestEnsureSectionFiles:
    def test_creates_missing_files(self, tmp_path):
        (tmp_path / "section").mkdir()
        manifest = {"sections": [{"slug": "01_intro", "title": "Introduction"}]}
        changes = ensure_section_files(manifest, str(tmp_path))
        assert (tmp_path / "section" / "01_intro.tex").exists()
        assert len(changes) == 1

    def test_skips_existing_files(self, tmp_path):
        section_dir = tmp_path / "section"
        section_dir.mkdir()
        (section_dir / "01_intro.tex").write_text("existing")
        manifest = {"sections": [{"slug": "01_intro", "title": "Introduction"}]}
        changes = ensure_section_files(manifest, str(tmp_path))
        assert changes == []
        assert (section_dir / "01_intro.tex").read_text() == "existing"

    def test_abstract_uses_abstract_environment(self, tmp_path):
        (tmp_path / "section").mkdir()
        manifest = {"sections": [{"slug": "00_abstract", "title": "Abstract"}]}
        ensure_section_files(manifest, str(tmp_path))
        content = (tmp_path / "section" / "00_abstract.tex").read_text()
        assert "\\begin{abstract}" in content

    def test_dry_run_does_not_create(self, tmp_path):
        (tmp_path / "section").mkdir()
        manifest = {"sections": [{"slug": "01_intro", "title": "Introduction"}]}
        changes = ensure_section_files(manifest, str(tmp_path), dry_run=True)
        assert not (tmp_path / "section" / "01_intro.tex").exists()
        assert "Would create" in changes[0]


# ---------------------------------------------------------------------------
# End-to-end sync
# ---------------------------------------------------------------------------

MAIN_TEX_WITH_MARKERS = (
    "\\documentclass{article}\n"
    "% BEGIN SYNC: bibliography\n"
    "\\usepackage[backend=biber,style=numeric,sorting=nyt,maxbibnames=99]{biblatex}\n"
    "\\addbibresource{bibliography.bib}\n"
    "% END SYNC: bibliography\n"
    "% BEGIN SYNC: metadata\n"
    "% Paper metadata\n"
    "\\newcommand{\\papertitle}{Old Title}\n"
    "\\newcommand{\\paperauthors}{Old Author}\n"
    "% END SYNC: metadata\n"
    "% BEGIN SYNC: macros\n"
    "% END SYNC: macros\n"
    "% BEGIN SYNC: styles\n"
    "% END SYNC: styles\n"
    "\\begin{document}\n"
    "% BEGIN SYNC: author-block\n"
    "\\title{\\papertitle}\n"
    "\\author{\\paperauthors}\n"
    "\\maketitle\n"
    "% END SYNC: author-block\n"
    "% BEGIN SYNC: sections\n"
    "\\input{section/00_abstract}\n"
    "% END SYNC: sections\n"
    "\\end{document}\n"
)


class TestSyncEndToEnd:
    def test_updates_all_regions(self, tmp_project):
        (tmp_project / "main.tex").write_text(MAIN_TEX_WITH_MARKERS)
        sync(str(tmp_project))
        result = (tmp_project / "main.tex").read_text()
        assert "Test Paper" in result
        assert "Old Title" not in result
        assert "\\newcommand{\\NumModels}{5}" in result
        assert "\\input{section/01_introduction}" in result
        assert "\\usepackage{styles/messageboxes}" in result

    def test_creates_section_files(self, tmp_project):
        (tmp_project / "main.tex").write_text(MAIN_TEX_WITH_MARKERS)
        sync(str(tmp_project))
        assert (tmp_project / "section" / "00_abstract.tex").exists()
        assert (tmp_project / "section" / "01_introduction.tex").exists()

    def test_idempotent(self, tmp_project):
        (tmp_project / "main.tex").write_text(MAIN_TEX_WITH_MARKERS)
        sync(str(tmp_project))
        after_first = (tmp_project / "main.tex").read_text()
        sync(str(tmp_project))
        assert (tmp_project / "main.tex").read_text() == after_first

    def test_template_aware_author_block(self, tmp_project):
        yaml_content = (tmp_project / "paper.yaml").read_text()
        (tmp_project / "paper.yaml").write_text(
            yaml_content.replace("template: article", "template: neurips2024")
        )
        (tmp_project / "main.tex").write_text(MAIN_TEX_WITH_MARKERS)
        sync(str(tmp_project))
        result = (tmp_project / "main.tex").read_text()
        assert "\\And" in result
        assert "MIT" in result
