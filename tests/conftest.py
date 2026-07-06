"""Shared fixtures for agentic-latex tests."""

from __future__ import annotations

import os
import sys

import pytest

# Add scripts/ to path so we can import sync, stats, cite, etc.
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS_DIR)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project structure in a temp directory."""
    # paper.yaml
    (tmp_path / "paper.yaml").write_text(
        'template: article\n'
        'title: "Test Paper"\n'
        'authors:\n'
        '  - name: "Alice Smith"\n'
        '    affiliation: "MIT"\n'
        '    email: "alice@mit.edu"\n'
        '  - name: "Bob Jones"\n'
        '    affiliation: "Stanford"\n'
        '    email: "bob@stanford.edu"\n'
        'sections:\n'
        '  - slug: "00_abstract"\n'
        '    title: "Abstract"\n'
        '    status: draft\n'
        '  - slug: "01_introduction"\n'
        '    title: "Introduction"\n'
        '    status: draft\n'
        'macros:\n'
        '  NumModels: "5"\n'
        '  DatasetSize: "10{,}000"\n'
        'styles:\n'
        '  - messageboxes\n'
        'bibliography:\n'
        '  backend: biber\n'
        '  style: numeric\n'
        '  sorting: nyt\n'
        '  maxbibnames: 99\n'
        '  file: bibliography.bib\n'
    )

    # section dir
    section_dir = tmp_path / "section"
    section_dir.mkdir()

    # templates/article
    tpl_dir = tmp_path / "templates" / "article"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "template.yaml").write_text(
        'name: "Article"\n'
        'author_format: article\n'
        'bibliography_system: biblatex\n'
        'extra_files: []\n'
    )

    # templates/neurips2024
    neurips_dir = tmp_path / "templates" / "neurips2024"
    neurips_dir.mkdir(parents=True)
    (neurips_dir / "template.yaml").write_text(
        'name: "NeurIPS 2024"\n'
        'author_format: neurips\n'
        'bibliography_system: natbib\n'
        'extra_files: []\n'
    )

    return tmp_path
