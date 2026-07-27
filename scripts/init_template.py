#!/usr/bin/env python3
"""Initialize project from a conference template.

Copies template main.tex and .cls/.sty files to the project root,
updates paper.yaml, and runs sync to populate content.

Usage:
    python3 scripts/init_template.py <template-name> [--project-root PATH]
    python3 scripts/init_template.py --list
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from typing import Any

import yaml


def list_templates(project_root: str) -> None:
    """Print a table of available templates with descriptions."""
    templates_dir = os.path.join(project_root, "templates")
    if not os.path.isdir(templates_dir):
        print("No templates directory found.", file=sys.stderr)
        return

    print("Available templates:\n")
    for name in sorted(os.listdir(templates_dir)):
        tpl_dir = os.path.join(templates_dir, name)
        if not os.path.isdir(tpl_dir):
            continue
        config_path = os.path.join(tpl_dir, "template.yaml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            desc = config.get("description", "")
            print(f"  {name:20s} {desc}")
        else:
            print(f"  {name:20s} (no template.yaml)")


def _get_old_extra_files(project_root: str, manifest: dict[str, Any]) -> list[str]:
    """Return the extra_files list from the currently active template."""
    old_template = manifest.get("template", "article")
    old_config_path = os.path.join(
        project_root, "templates", old_template, "template.yaml"
    )
    if os.path.exists(old_config_path):
        with open(old_config_path) as f:
            old_config = yaml.safe_load(f) or {}
        return old_config.get("extra_files", [])
    return []


def _update_paper_yaml(manifest_path: str, template_name: str) -> None:
    """Update the template field in paper.yaml via regex to preserve formatting."""
    with open(manifest_path) as f:
        content = f.read()

    new_content = re.sub(
        r"^template:\s*.*$",
        f"template: {template_name}",
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if new_content == content and "template:" not in content:
        new_content = f"template: {template_name}\n\n{content}"

    with open(manifest_path, "w") as f:
        f.write(new_content)


def init_template(project_root: str, template_name: str) -> int:
    """Switch the project to a conference template.

    Copies the template's main.tex and style files, cleans up files from
    the previous template, updates paper.yaml, and runs sync.

    Returns 0 on success, 1 on error.
    """
    templates_dir = os.path.join(project_root, "templates")
    tpl_dir = os.path.join(templates_dir, template_name)

    if not os.path.isdir(tpl_dir):
        print(
            f"ERROR: Template '{template_name}' not found in templates/",
            file=sys.stderr,
        )
        available = sorted(
            d
            for d in os.listdir(templates_dir)
            if os.path.isdir(os.path.join(templates_dir, d))
        )
        print(f"Available: {', '.join(available)}", file=sys.stderr)
        return 1

    config_path = os.path.join(tpl_dir, "template.yaml")
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found", file=sys.stderr)
        return 1

    with open(config_path) as f:
        config: dict[str, Any] = yaml.safe_load(f) or {}

    tpl_main = os.path.join(tpl_dir, "main.tex")
    if not os.path.exists(tpl_main):
        print(f"ERROR: {tpl_main} not found", file=sys.stderr)
        return 1

    print(f"Initializing template: {config.get('name', template_name)}")

    # Step 1: Clean up old template's extra files
    manifest_path = os.path.join(project_root, "paper.yaml")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest: dict[str, Any] = yaml.safe_load(f) or {}
        new_files = config.get("extra_files", [])
        for old_file in _get_old_extra_files(project_root, manifest):
            if old_file not in new_files:
                old_path = os.path.join(project_root, old_file)
                if os.path.exists(old_path):
                    os.remove(old_path)
                    print(f"  Removed: {old_file}")

    # Step 2: Copy main.tex
    shutil.copy2(tpl_main, os.path.join(project_root, "main.tex"))
    print("  Copied: main.tex")

    # Step 3: Copy extra files (.cls, .sty, etc.)
    for filename in config.get("extra_files", []):
        src = os.path.join(tpl_dir, filename)
        dst = os.path.join(project_root, filename)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  Copied: {filename}")
        else:
            print(f"  WARNING: {filename} not found in template", file=sys.stderr)

    # Step 4: Update paper.yaml (preserves formatting)
    if os.path.exists(manifest_path):
        _update_paper_yaml(manifest_path, template_name)
        print(f"  Updated: paper.yaml (template: {template_name})")

    # Step 5: Run sync
    print("  Running sync...")
    scripts_dir = os.path.join(project_root, "scripts")
    sys.path.insert(0, scripts_dir)
    from sync import sync as run_sync

    result = run_sync(project_root)

    if result == 0:
        print(f"\nTemplate '{template_name}' initialized successfully.")
        print("Run 'bash scripts/build.sh' to compile.")
    else:
        print("\nTemplate initialized but sync reported errors.", file=sys.stderr)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize project from a conference template"
    )
    parser.add_argument(
        "template", nargs="?", help="Template name (e.g., neurips2024, ieee, acm)"
    )
    parser.add_argument("--project-root", default=None, help="Project root directory")
    parser.add_argument("--list", action="store_true", help="List available templates")
    args = parser.parse_args()

    root = args.project_root or os.getcwd()

    if args.list:
        list_templates(root)
        return

    if not args.template:
        parser.error("template name required (use --list to see available)")

    sys.exit(init_template(root, args.template))


if __name__ == "__main__":
    main()
