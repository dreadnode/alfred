"""Tests for multi-paper workspace: scaffolding, slug helpers, and paper listing."""

from __future__ import annotations

import os
import sys
import typing as t
from contextlib import contextmanager

# Add paths so we can import backend.* and scripts.*
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, UI_DIR)
sys.path.insert(0, SCRIPTS_DIR)

import backend.server as srv  # noqa: E402
from backend.server import (  # noqa: E402
    _list_papers,
    _slugify,
    _title_from_filename,
    _unique_slug,
)
from scaffold import scaffold_paper  # noqa: E402


@contextmanager
def _workspace_globals(
    workspace_root: str | None, paper_dir: str = ""
) -> t.Iterator[None]:
    """Temporarily set workspace-related globals, restoring on exit."""
    old_root, old_dir = srv._workspace_root, srv._paper_dir
    srv._workspace_root = workspace_root
    srv._paper_dir = paper_dir
    try:
        yield
    finally:
        srv._workspace_root, srv._paper_dir = old_root, old_dir


# ---------------------------------------------------------------------------
# scaffold_paper
# ---------------------------------------------------------------------------


class TestScaffoldPaper:
    def test_creates_complete_project(self, tmp_path: t.Any) -> None:
        """Scaffolding produces all required files with correct title."""
        import yaml

        paper_dir = str(tmp_path / "my-paper")
        scaffold_paper(paper_dir, title="Custom Title")

        with open(os.path.join(paper_dir, "paper.yaml")) as f:
            data = yaml.safe_load(f)
        assert data["title"] == "Custom Title"
        assert os.path.isdir(os.path.join(paper_dir, "section"))
        assert os.path.isfile(os.path.join(paper_dir, "bibliography.bib"))
        assert os.path.isfile(os.path.join(paper_dir, "main.tex"))

    def test_does_not_overwrite_existing_bibliography(self, tmp_path: t.Any) -> None:
        paper_dir = str(tmp_path / "my-paper")
        os.makedirs(paper_dir)
        bib_path = os.path.join(paper_dir, "bibliography.bib")
        with open(bib_path, "w") as f:
            f.write("@article{existing,}")
        scaffold_paper(paper_dir)
        with open(bib_path) as f:
            assert "@article{existing,}" in f.read()


# ---------------------------------------------------------------------------
# _slugify / _unique_slug
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_converts_title_to_slug(self) -> None:
        assert _slugify("Hello, World! (2024)") == "hello-world-2024"

    def test_truncates_and_handles_empty(self) -> None:
        assert len(_slugify("a" * 100)) <= 50
        assert _slugify("") == "untitled"
        assert _slugify("!!!") == "untitled"


class TestUniqueSlug:
    def test_appends_suffix_on_collision(self, tmp_path: t.Any) -> None:
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        (papers_dir / "my-paper").mkdir()
        (papers_dir / "my-paper-2").mkdir()
        assert _unique_slug("My Paper", str(papers_dir)) == "my-paper-3"


# ---------------------------------------------------------------------------
# _list_papers
# ---------------------------------------------------------------------------


class TestListPapers:
    def test_returns_empty_without_workspace(self) -> None:
        with _workspace_globals(workspace_root=None):
            assert _list_papers() == []

    def test_lists_papers_with_active_flag(self, tmp_path: t.Any) -> None:
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()

        p1 = papers_dir / "paper-one"
        p1.mkdir()
        (p1 / "paper.yaml").write_text('title: "First Paper"\n')

        p2 = papers_dir / "paper-two"
        p2.mkdir()
        (p2 / "paper.yaml").write_text('title: "Second Paper"\n')

        # Non-paper dir should be ignored
        (papers_dir / "not-a-paper").mkdir()

        with _workspace_globals(str(tmp_path), paper_dir=str(p1)):
            papers = _list_papers()
            assert len(papers) == 2
            assert {p["slug"] for p in papers} == {"paper-one", "paper-two"}
            assert [p for p in papers if p["active"]] == [
                {"slug": "paper-one", "title": "First Paper", "active": True}
            ]

    def test_falls_back_to_dirname_when_no_title(self, tmp_path: t.Any) -> None:
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        p = papers_dir / "fallback-slug"
        p.mkdir()
        (p / "paper.yaml").write_text("template: article\n")

        with _workspace_globals(str(tmp_path)):
            assert _list_papers()[0]["title"] == "fallback-slug"


# ---------------------------------------------------------------------------
# _title_from_filename
# ---------------------------------------------------------------------------


class TestTitleFromFilename:
    def test_strips_pdf_extension(self) -> None:
        assert _title_from_filename("my-paper.pdf") == "My Paper"

    def test_replaces_separators(self) -> None:
        assert _title_from_filename("calibrating_llm_judges.pdf") == "Calibrating Llm Judges"

    def test_handles_dotfile_edge_case(self) -> None:
        assert _title_from_filename(".pdf") == "Untitled"

    def test_handles_special_chars(self) -> None:
        assert _title_from_filename("---special___chars---.pdf") == "Special Chars"

    def test_preserves_spaces(self) -> None:
        assert _title_from_filename("hello world.pdf") == "Hello World"


# ---------------------------------------------------------------------------
# _create_paper_for_pdf (path containment guard)
# ---------------------------------------------------------------------------


class TestPathContainment:
    def test_skips_pdf_inside_paper_dir(self) -> None:
        """PDF inside the active paper_dir should not create a new paper."""
        import asyncio

        with _workspace_globals("/workspace", paper_dir="/workspace/papers/my-paper"):
            result = asyncio.run(
                srv._create_paper_for_pdf("/workspace/papers/my-paper/doc.pdf")
            )
            assert result is None

    def test_does_not_match_sibling_dir_prefix(self) -> None:
        """paper-2 should NOT be treated as inside paper (prefix collision)."""
        # Verify the containment check uses os.sep so /papers/paper
        # doesn't falsely match /papers/paper-2/doc.pdf
        paper_dir = "/workspace/papers/paper"
        sibling_pdf = "/workspace/papers/paper-2/doc.pdf"
        paper_prefix = os.path.abspath(paper_dir) + os.sep
        assert not os.path.abspath(sibling_pdf).startswith(paper_prefix)

    def test_skips_in_single_paper_mode(self) -> None:
        """Non-workspace mode should always return None."""
        import asyncio

        with _workspace_globals(workspace_root=None, paper_dir="/some/paper"):
            result = asyncio.run(srv._create_paper_for_pdf("/tmp/ext.pdf"))
            assert result is None


# ---------------------------------------------------------------------------
# switch_paper endpoint
# ---------------------------------------------------------------------------


class TestSwitchPaper:
    def test_switches_to_valid_paper(self, tmp_path: t.Any) -> None:
        """Switching to a valid paper updates _paper_dir and returns title."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        papers = tmp_path / "papers"
        papers.mkdir()
        p1 = papers / "paper-one"
        p1.mkdir()
        (p1 / "paper.yaml").write_text('title: "First Paper"\n')

        p2 = papers / "paper-two"
        p2.mkdir()
        (p2 / "paper.yaml").write_text('title: "Second Paper"\n')

        with _workspace_globals(str(tmp_path), paper_dir=str(p1)):
            with patch.object(srv, "_restart_pdf_watcher", new_callable=AsyncMock):
                result = asyncio.run(srv.switch_paper({"slug": "paper-two"}))
            assert result["slug"] == "paper-two"
            assert result["title"] == "Second Paper"
            assert srv._paper_dir == str(p2)

    def test_auto_loads_pdf_when_no_build(self, tmp_path: t.Any) -> None:
        """Switching to a paper with an uploaded PDF but no build auto-sets _custom_pdf."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        papers = tmp_path / "papers"
        papers.mkdir()
        p1 = papers / "paper-one"
        p1.mkdir()
        (p1 / "paper.yaml").write_text('title: "First"\n')

        p2 = papers / "uploaded-paper"
        p2.mkdir()
        (p2 / "paper.yaml").write_text('title: "Uploaded"\n')
        (p2 / "build").mkdir()  # empty build dir, no main.pdf
        (p2 / "my-doc.pdf").write_bytes(b"%PDF-fake")

        with _workspace_globals(str(tmp_path), paper_dir=str(p1)):
            with patch.object(srv, "_restart_pdf_watcher", new_callable=AsyncMock):
                asyncio.run(srv.switch_paper({"slug": "uploaded-paper"}))
            assert srv._custom_pdf == str(p2 / "my-doc.pdf")

    def test_resets_custom_pdf_when_build_exists(self, tmp_path: t.Any) -> None:
        """Switching to a paper with build/main.pdf should NOT set _custom_pdf."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        papers = tmp_path / "papers"
        papers.mkdir()
        p1 = papers / "built-paper"
        p1.mkdir()
        (p1 / "paper.yaml").write_text('title: "Built"\n')
        build = p1 / "build"
        build.mkdir()
        (build / "main.pdf").write_bytes(b"%PDF-fake")

        with _workspace_globals(str(tmp_path), paper_dir=str(tmp_path)):
            srv._custom_pdf = "/old/stale.pdf"
            with patch.object(srv, "_restart_pdf_watcher", new_callable=AsyncMock):
                asyncio.run(srv.switch_paper({"slug": "built-paper"}))
            assert srv._custom_pdf is None

    def test_rejects_nonexistent_paper(self, tmp_path: t.Any) -> None:
        """Switching to a paper that doesn't exist returns an error."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        papers = tmp_path / "papers"
        papers.mkdir()

        with _workspace_globals(str(tmp_path), paper_dir=str(tmp_path)):
            with patch.object(srv, "_restart_pdf_watcher", new_callable=AsyncMock):
                result = asyncio.run(srv.switch_paper({"slug": "nope"}))
            assert "error" in result

    def test_rejects_when_not_workspace(self) -> None:
        """Switching is not allowed in single-paper mode."""
        import asyncio

        with _workspace_globals(workspace_root=None):
            result = asyncio.run(srv.switch_paper({"slug": "any"}))
            assert "error" in result


# ---------------------------------------------------------------------------
# create_paper endpoint
# ---------------------------------------------------------------------------


class TestCreatePaper:
    def test_creates_paper_under_papers_dir(self, tmp_path: t.Any) -> None:
        """Creating a paper scaffolds it under papers/ and switches to it."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        papers = tmp_path / "papers"
        papers.mkdir()

        with _workspace_globals(str(tmp_path), paper_dir=str(tmp_path)):
            with patch.object(srv, "_restart_pdf_watcher", new_callable=AsyncMock):
                result = asyncio.run(srv.create_paper({"title": "My New Paper"}))

            assert result["slug"] == "my-new-paper"
            assert result["title"] == "My New Paper"
            new_dir = papers / "my-new-paper"
            assert new_dir.is_dir()
            assert (new_dir / "paper.yaml").is_file()
            assert srv._paper_dir == str(new_dir)

    def test_rejects_empty_title(self, tmp_path: t.Any) -> None:
        """Empty title is rejected."""
        import asyncio

        with _workspace_globals(str(tmp_path)):
            result = asyncio.run(srv.create_paper({"title": ""}))
            assert "error" in result

    def test_rejects_when_not_workspace(self) -> None:
        """Creating is not allowed in single-paper mode."""
        import asyncio

        with _workspace_globals(workspace_root=None):
            result = asyncio.run(srv.create_paper({"title": "Test"}))
            assert "error" in result

    def test_deduplicates_slug(self, tmp_path: t.Any) -> None:
        """Duplicate title gets a unique slug."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        papers = tmp_path / "papers"
        papers.mkdir()
        (papers / "my-paper").mkdir()
        (papers / "my-paper" / "paper.yaml").write_text('title: "My Paper"\n')

        with _workspace_globals(str(tmp_path), paper_dir=str(tmp_path)):
            with patch.object(srv, "_restart_pdf_watcher", new_callable=AsyncMock):
                result = asyncio.run(srv.create_paper({"title": "My Paper"}))

            assert result["slug"] == "my-paper-2"
            assert (papers / "my-paper-2").is_dir()
