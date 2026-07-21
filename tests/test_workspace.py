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

import backend.server as srv
from backend.server import _list_papers, _slugify, _unique_slug
from scaffold import scaffold_paper


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
        (tmp_path / "my-paper").mkdir()
        (tmp_path / "my-paper-2").mkdir()
        assert _unique_slug("My Paper", str(tmp_path)) == "my-paper-3"


# ---------------------------------------------------------------------------
# _list_papers
# ---------------------------------------------------------------------------


class TestListPapers:
    def test_returns_empty_without_workspace(self) -> None:
        with _workspace_globals(workspace_root=None):
            assert _list_papers() == []

    def test_lists_papers_with_active_flag(self, tmp_path: t.Any) -> None:
        p1 = tmp_path / "paper-one"
        p1.mkdir()
        (p1 / "paper.yaml").write_text('title: "First Paper"\n')

        p2 = tmp_path / "paper-two"
        p2.mkdir()
        (p2 / "paper.yaml").write_text('title: "Second Paper"\n')

        # Non-paper dir should be ignored
        (tmp_path / "not-a-paper").mkdir()

        with _workspace_globals(str(tmp_path), paper_dir=str(p1)):
            papers = _list_papers()
            assert len(papers) == 2
            assert {p["slug"] for p in papers} == {"paper-one", "paper-two"}
            assert [p for p in papers if p["active"]] == [
                {"slug": "paper-one", "title": "First Paper", "active": True}
            ]

    def test_falls_back_to_dirname_when_no_title(self, tmp_path: t.Any) -> None:
        p = tmp_path / "fallback-slug"
        p.mkdir()
        (p / "paper.yaml").write_text("template: article\n")

        with _workspace_globals(str(tmp_path)):
            assert _list_papers()[0]["title"] == "fallback-slug"
