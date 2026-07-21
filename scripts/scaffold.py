"""Scaffold a minimal paper project.

Shared by the CLI launcher (``scripts/ui.py``) and the backend server
(``ui/backend/server.py``) so that papers can be created both at startup
and at runtime without circular imports.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import yaml

MINIMAL_PAPER_YAML: dict = {
    "template": "article",
    "title": "Untitled Paper",
    "authors": [],
    "abstract_summary": "",
    "sections": [],
    "bibliography": {"file": "bibliography.bib"},
    "build": {"engine": "pdflatex", "output_dir": "build"},
}


def scaffold_paper(paper_dir: str, title: str = "Untitled Paper") -> None:
    """Create a minimal paper project so the UI has something to work with.

    Works independently of the repo layout — copies template files directly
    and calls ``sync`` without going through ``init_template`` (which
    expects ``templates/`` inside the project root).
    """
    repo_root = str(Path(__file__).resolve().parent.parent)
    os.makedirs(paper_dir, exist_ok=True)

    # Write paper.yaml.
    manifest = dict(MINIMAL_PAPER_YAML, title=title)
    manifest_path = os.path.join(paper_dir, "paper.yaml")
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

    # Create section/ and empty bibliography.bib if missing.
    os.makedirs(os.path.join(paper_dir, "section"), exist_ok=True)
    bib_path = os.path.join(paper_dir, "bibliography.bib")
    if not os.path.exists(bib_path):
        Path(bib_path).touch()

    # Copy main.tex from the article template.
    tpl_dir = os.path.join(repo_root, "templates", "article")
    shutil.copy2(os.path.join(tpl_dir, "main.tex"), os.path.join(paper_dir, "main.tex"))

    # Copy any extra template files (.cls, .sty).
    tpl_config_path = os.path.join(tpl_dir, "template.yaml")
    if os.path.isfile(tpl_config_path):
        with open(tpl_config_path) as f:
            tpl_config = yaml.safe_load(f) or {}
        for extra in tpl_config.get("extra_files", []):
            src = os.path.join(tpl_dir, extra)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(paper_dir, extra))

    # Run sync to populate managed regions in main.tex.
    scripts_dir = os.path.join(repo_root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from sync import sync as run_sync

    run_sync(paper_dir)
    print(f"  Scaffolded: {paper_dir}")
