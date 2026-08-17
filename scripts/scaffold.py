"""Scaffold a minimal paper project.

Shared by the CLI launcher (``scripts/ui.py``) and the backend server
(``ui/backend/server.py``) so that papers can be created both at startup
and at runtime without circular imports.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
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


def _populate_paper(paper_dir: str, title: str, repo_root: str) -> None:
    """Build a complete paper inside an isolated staging directory."""
    # Write paper.yaml.
    manifest = dict(MINIMAL_PAPER_YAML, title=title)
    manifest_path = os.path.join(paper_dir, "paper.yaml")
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

    # Create the standard paper-owned directories and empty bibliography.
    for dirname in ("section", "data", "figures", "reviews", "styles"):
        os.makedirs(os.path.join(paper_dir, dirname), exist_ok=True)
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

    if run_sync(paper_dir) != 0:
        raise RuntimeError("Failed to synchronize the scaffolded paper")


def scaffold_paper(paper_dir: str, title: str = "Untitled Paper") -> None:
    """Create a complete paper project and publish it atomically.

    The project is assembled in a sibling staging directory so failures do
    not expose partially created paper files. Existing non-paper content is
    preserved by copying it into the staged project before the final swap.
    """
    paper_dir = os.path.abspath(paper_dir)
    repo_root = str(Path(__file__).resolve().parent.parent)
    for managed_name in ("paper.yaml", "main.tex"):
        managed_path = os.path.join(paper_dir, managed_name)
        if os.path.exists(managed_path):
            raise FileExistsError(
                f"Refusing to overwrite existing paper file: {managed_path}"
            )

    target_exists = os.path.exists(paper_dir)
    if target_exists and not os.path.isdir(paper_dir):
        raise NotADirectoryError(f"Paper path is not a directory: {paper_dir}")

    parent = os.path.dirname(paper_dir)
    os.makedirs(parent, exist_ok=True)
    basename = os.path.basename(paper_dir) or "paper"
    staging_dir = tempfile.mkdtemp(prefix=f".{basename}.scaffold-", dir=parent)
    backup_dir: str | None = None
    committed = False

    try:
        if target_exists:
            shutil.copytree(paper_dir, staging_dir, dirs_exist_ok=True, symlinks=True)
        _populate_paper(staging_dir, title, repo_root)

        if target_exists:
            backup_dir = tempfile.mkdtemp(prefix=f".{basename}.original-", dir=parent)
            os.rmdir(backup_dir)
            os.replace(paper_dir, backup_dir)
            try:
                os.replace(staging_dir, paper_dir)
            except BaseException:
                os.replace(backup_dir, paper_dir)
                backup_dir = None
                raise
        else:
            os.replace(staging_dir, paper_dir)

        committed = True
    finally:
        if not committed and os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir)
        if committed and backup_dir is not None:
            try:
                shutil.rmtree(backup_dir)
            except OSError as exc:
                print(
                    f"  Warning: could not remove scaffold backup {backup_dir}: {exc}",
                    file=sys.stderr,
                )

    print(f"  Scaffolded: {paper_dir}")
