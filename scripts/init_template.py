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
import tempfile
from typing import Any

import yaml

# Templates live in the repo, not in per-paper directories.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_EXTRA_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class _RollbackError(RuntimeError):
    """Raised when a failed commit could not restore every original path."""


def _template_dir(template_name: str) -> str | None:
    """Return a template directory only for a safe, installed template name."""
    if not _TEMPLATE_NAME_RE.fullmatch(template_name):
        return None
    path = os.path.join(_REPO_ROOT, "templates", template_name)
    return path if os.path.isdir(path) else None


def list_templates() -> None:
    """Print a table of available templates with descriptions."""
    templates_dir = os.path.join(_REPO_ROOT, "templates")
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


def _get_extra_files(config: dict[str, Any], template_name: str) -> list[str]:
    """Return a validated list of template-owned root-level files."""
    raw_files = config.get("extra_files", [])
    if not isinstance(raw_files, list):
        raise ValueError(f"Template '{template_name}' has an invalid extra_files list")

    files: list[str] = []
    for filename in raw_files:
        if not isinstance(filename, str) or not _EXTRA_FILE_RE.fullmatch(filename):
            raise ValueError(
                f"Template '{template_name}' has an invalid extra file: {filename!r}"
            )
        files.append(filename)
    return files


def _get_old_extra_files(manifest: dict[str, Any]) -> list[str]:
    """Return the extra_files list from the currently active template."""
    old_template = manifest.get("template", "article")
    old_dir = _template_dir(old_template) if isinstance(old_template, str) else None
    if old_dir is None:
        return []
    old_config_path = os.path.join(old_dir, "template.yaml")
    if os.path.exists(old_config_path):
        with open(old_config_path) as f:
            old_config = yaml.safe_load(f) or {}
        if not isinstance(old_config, dict):
            raise ValueError(f"Template '{old_template}' has an invalid configuration")
        return _get_extra_files(old_config, old_template)
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


def _copy_file_atomic(source: str, destination: str) -> None:
    """Atomically copy one staged file into its live destination."""
    directory = os.path.dirname(destination)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination)}.", dir=directory
    )
    os.close(fd)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    except BaseException:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def _staged_additions(
    staged_root: str, project_root: str, dirname: str
) -> dict[str, str]:
    """Return files created by sync in a staged paper subdirectory."""
    additions: dict[str, str] = {}
    staged_dir = os.path.join(staged_root, dirname)
    if not os.path.isdir(staged_dir):
        return additions

    for root, _, filenames in os.walk(staged_dir):
        for filename in filenames:
            source = os.path.join(root, filename)
            relative = os.path.relpath(source, staged_root)
            destination = os.path.join(project_root, relative)
            if not os.path.lexists(destination):
                additions[destination] = source
    return additions


def _commit_template_switch(
    project_root: str,
    writes: dict[str, str],
    deletions: set[str],
    transaction_dir: str,
) -> bool:
    """Apply staged files, restoring the exact original state on failure."""
    touched = sorted(set(writes) | deletions)
    for destination in touched:
        if os.path.isdir(destination) and not os.path.islink(destination):
            raise IsADirectoryError(
                f"Template-managed file is a directory: {destination}"
            )

    backup_root = os.path.join(transaction_dir, "originals")
    os.makedirs(backup_root)
    originals: dict[str, str] = {}
    published: set[str] = set()
    created_dirs: set[str] = set()
    build_dir = os.path.join(project_root, "build")
    build_backup = os.path.join(transaction_dir, "build")
    build_moved = False

    try:
        for index, destination in enumerate(touched):
            if os.path.lexists(destination):
                backup = os.path.join(backup_root, str(index))
                os.replace(destination, backup)
                originals[destination] = backup

        for destination, source in writes.items():
            parent = os.path.dirname(destination)
            if not os.path.isdir(parent):
                os.makedirs(parent)
                created_dirs.add(parent)
            _copy_file_atomic(source, destination)
            published.add(destination)

        if os.path.isdir(build_dir):
            os.replace(build_dir, build_backup)
            build_moved = True
    except BaseException as exc:
        rollback_errors: list[str] = []

        if build_moved:
            try:
                os.replace(build_backup, build_dir)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))

        for destination in reversed(touched):
            try:
                backup = originals.get(destination)
                if destination in published and os.path.lexists(destination):
                    os.unlink(destination)
                if backup is not None:
                    if os.path.lexists(destination):
                        os.unlink(destination)
                    os.replace(backup, destination)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))

        for directory in sorted(created_dirs, key=len, reverse=True):
            try:
                os.rmdir(directory)
            except OSError:
                pass

        if rollback_errors:
            details = "; ".join(rollback_errors)
            raise _RollbackError(
                f"Template switch failed and rollback was incomplete: {details}"
            ) from exc
        raise

    return build_moved


def init_template(project_root: str, template_name: str) -> int:
    """Switch the project to a conference template.

    Copies the template's main.tex and style files, cleans up files from
    the previous template, updates paper.yaml, and runs sync.

    Returns 0 on success, 1 on error.
    """
    project_root = os.path.abspath(project_root)
    templates_dir = os.path.join(_REPO_ROOT, "templates")
    tpl_dir = _template_dir(template_name)

    if tpl_dir is None:
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

    try:
        with open(config_path) as f:
            loaded_config = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not isinstance(loaded_config, dict):
        print(f"ERROR: {config_path} is not a mapping", file=sys.stderr)
        return 1
    config: dict[str, Any] = loaded_config

    tpl_main = os.path.join(tpl_dir, "main.tex")
    if not os.path.exists(tpl_main):
        print(f"ERROR: {tpl_main} not found", file=sys.stderr)
        return 1

    manifest_path = os.path.join(project_root, "paper.yaml")
    main_path = os.path.join(project_root, "main.tex")
    if not os.path.isfile(manifest_path) or not os.path.isfile(main_path):
        print("ERROR: Project must contain paper.yaml and main.tex", file=sys.stderr)
        return 1

    try:
        with open(manifest_path) as f:
            loaded_manifest = yaml.safe_load(f) or {}
        if not isinstance(loaded_manifest, dict):
            raise ValueError("paper.yaml must contain a mapping")
        manifest: dict[str, Any] = loaded_manifest
        new_files = _get_extra_files(config, template_name)
        old_files = _get_old_extra_files(manifest)
        for filename in new_files:
            source = os.path.join(tpl_dir, filename)
            if not os.path.isfile(source):
                raise FileNotFoundError(
                    f"Template '{template_name}' is missing required file: {filename}"
                )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Initializing template: {config.get('name', template_name)}")
    parent = os.path.dirname(project_root)
    basename = os.path.basename(project_root) or "paper"
    transaction_dir = tempfile.mkdtemp(prefix=f".{basename}.template-", dir=parent)
    preserve_transaction = False

    try:
        staged_root = os.path.join(transaction_dir, "staged")
        os.makedirs(staged_root)
        shutil.copy2(manifest_path, os.path.join(staged_root, "paper.yaml"))
        shutil.copy2(tpl_main, os.path.join(staged_root, "main.tex"))

        for dirname in ("section", "styles"):
            source_dir = os.path.join(project_root, dirname)
            if os.path.isdir(source_dir):
                shutil.copytree(
                    source_dir,
                    os.path.join(staged_root, dirname),
                    symlinks=True,
                )

        for filename in new_files:
            shutil.copy2(
                os.path.join(tpl_dir, filename),
                os.path.join(staged_root, filename),
            )

        _update_paper_yaml(os.path.join(staged_root, "paper.yaml"), template_name)

        scripts_dir = os.path.join(_REPO_ROOT, "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from sync import sync as run_sync

        print("  Validating staged template with sync...")
        if run_sync(staged_root) != 0:
            raise RuntimeError("sync reported errors")

        writes = {
            os.path.join(project_root, "main.tex"): os.path.join(
                staged_root, "main.tex"
            ),
            os.path.join(project_root, "paper.yaml"): os.path.join(
                staged_root, "paper.yaml"
            ),
        }
        for filename in new_files:
            writes[os.path.join(project_root, filename)] = os.path.join(
                staged_root, filename
            )
        writes.update(_staged_additions(staged_root, project_root, "section"))
        writes.update(_staged_additions(staged_root, project_root, "styles"))

        removed_files = [
            filename
            for filename in old_files
            if filename not in new_files
            and os.path.lexists(os.path.join(project_root, filename))
        ]
        deletions = {os.path.join(project_root, filename) for filename in removed_files}
        build_removed = _commit_template_switch(
            project_root,
            writes,
            deletions,
            transaction_dir,
        )
    except _RollbackError as exc:
        preserve_transaction = True
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            f"Recovery files were preserved at: {transaction_dir}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"ERROR: Template switch rolled back: {exc}", file=sys.stderr)
        return 1
    finally:
        if not preserve_transaction:
            try:
                shutil.rmtree(transaction_dir)
            except OSError as exc:
                print(
                    "WARNING: Could not remove template transaction files "
                    f"at {transaction_dir}: {exc}",
                    file=sys.stderr,
                )

    for filename in removed_files:
        print(f"  Removed: {filename}")
    if build_removed:
        print("  Cleaned: build/")
    print("  Copied: main.tex")
    for filename in new_files:
        print(f"  Copied: {filename}")
    print(f"  Updated: paper.yaml (template: {template_name})")
    print(f"\nTemplate '{template_name}' initialized successfully.")
    print("Run 'bash scripts/build.sh' to compile.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize project from a conference template"
    )
    parser.add_argument(
        "template", nargs="?", help="Template name (use --list to see all options)"
    )
    parser.add_argument("--project-root", default=None, help="Project root directory")
    parser.add_argument("--list", action="store_true", help="List available templates")
    args = parser.parse_args()

    root = args.project_root or os.getcwd()

    if args.list:
        list_templates()
        return

    if not args.template:
        parser.error("template name required (use --list to see available)")

    sys.exit(init_template(root, args.template))


if __name__ == "__main__":
    main()
