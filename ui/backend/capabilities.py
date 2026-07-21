"""Slash-command capability expansion for the web UI.

When a user message starts with ``/command``, this module reads the
capability's skill definition and guidance files, then assembles an
expanded prompt so the model receives full inline instructions.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, TypedDict

# Repo root — capabilities/ lives here.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class _CapabilityDef(TypedDict):
    description: str
    skill: str
    extra_files: list[str]
    args: Literal["required", "optional"]
    arg_label: str


CAPABILITIES: dict[str, _CapabilityDef] = {
    "search-sources": {
        "description": "Find relevant papers and sources",
        "skill": "capabilities/search-sources/skill.md",
        "extra_files": [
            "capabilities/shared/workflow-config.md",
            "capabilities/shared/search-strategy.md",
            "capabilities/search-sources/agent.md",
        ],
        "args": "required",
        "arg_label": "topic",
    },
    "analyze-source": {
        "description": "Deep-read a single source into a structured card",
        "skill": "capabilities/analyze-source/skill.md",
        "extra_files": [
            "capabilities/shared/workflow-config.md",
            "capabilities/shared/evidence-standards.md",
            "capabilities/shared/output-formats.md",
            "capabilities/analyze-source/agent.md",
        ],
        "args": "required",
        "arg_label": "source URL or file path",
    },
    "lit-review": {
        "description": "Full literature review workflow",
        "skill": "capabilities/lit-review/skill.md",
        "extra_files": [
            "capabilities/shared/workflow-config.md",
            "capabilities/shared/search-strategy.md",
            "capabilities/shared/evidence-standards.md",
            "capabilities/shared/output-formats.md",
            "capabilities/search-sources/agent.md",
            "capabilities/analyze-source/agent.md",
            "capabilities/shared/synthesizer.md",
        ],
        "args": "required",
        "arg_label": "topic",
    },
    "verify-claims": {
        "description": "Verify claims against evidence",
        "skill": "capabilities/verify-claims/skill.md",
        "extra_files": [
            "capabilities/shared/workflow-config.md",
            "capabilities/shared/search-strategy.md",
            "capabilities/shared/evidence-standards.md",
            "capabilities/shared/output-formats.md",
            "capabilities/search-sources/agent.md",
            "capabilities/analyze-source/agent.md",
            "capabilities/shared/synthesizer.md",
        ],
        "args": "required",
        "arg_label": "file path",
    },
    "peer-review": {
        "description": "Interactive peer review session",
        "skill": "capabilities/peer-review/skill.md",
        "extra_files": [
            "capabilities/shared/workflow-config.md",
            "capabilities/shared/output-formats.md",
            "capabilities/shared/evidence-standards.md",
        ],
        "args": "optional",
        "arg_label": "options",
    },
    "process-peer-review": {
        "description": "Process a peer review and record responses",
        "skill": "capabilities/process-peer-review/skill.md",
        "extra_files": [
            "capabilities/shared/workflow-config.md",
            "capabilities/shared/output-formats.md",
            "capabilities/shared/evidence-standards.md",
        ],
        "args": "optional",
        "arg_label": "review file path",
    },
    "detect-llm-writing": {
        "description": "Detect LLM writing indicators in prose",
        "skill": "capabilities/detect-llm-writing/skill.md",
        "extra_files": [
            "capabilities/detect-llm-writing/indicators.md",
        ],
        "args": "optional",
        "arg_label": "file or section",
    },
}

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_SLASH_RE = re.compile(r"^/([a-z][-a-z]*)\s*(.*)", re.DOTALL)


def parse_slash_command(text: str) -> tuple[str, str] | None:
    """Parse ``/command args`` from user input.

    Returns ``(command_name, arguments)`` or ``None`` if not a slash command.
    Strips surrounding quotes from the arguments if present.
    """
    m = _SLASH_RE.match(text.strip())
    if not m:
        return None
    command = m.group(1)
    args = m.group(2).strip()
    if len(args) >= 2 and args[0] == '"' and args[-1] == '"':
        args = args[1:-1]
    return (command, args)


# ---------------------------------------------------------------------------
# Expander
# ---------------------------------------------------------------------------


def _read_file(rel_path: str) -> str:
    """Read a file relative to the repo root, returning a placeholder on error."""
    full = os.path.join(_REPO_ROOT, rel_path)
    try:
        with open(full) as f:
            return f.read()
    except FileNotFoundError:
        return f"[File not found: {rel_path}]"


def maybe_expand_command(user_input: str) -> str:
    """Expand a ``/command`` into a full capability prompt.

    If the input is not a slash command or is an unknown command, returns
    an appropriate message.  Otherwise reads the capability's skill and
    guidance files and assembles an inline prompt.
    """
    parsed = parse_slash_command(user_input)
    if parsed is None:
        return user_input

    command, args = parsed

    if command not in CAPABILITIES:
        available = ", ".join(f"/{name}" for name in sorted(CAPABILITIES))
        return f"Unknown command: /{command}\nAvailable commands: {available}"

    cap = CAPABILITIES[command]

    if cap["args"] == "required" and not args:
        return (
            f"The /{command} command requires a {cap['arg_label']} argument.\n"
            f'Usage: /{command} "{cap["arg_label"]}"'
        )

    # Read skill.md
    skill_content = _read_file(cap["skill"])

    # Read extra guidance files
    guidance_sections: list[str] = []
    for rel_path in cap["extra_files"]:
        filename = os.path.basename(rel_path)
        content = _read_file(rel_path)
        guidance_sections.append(f"## Guidance: {filename}\n\n{content}")

    guidance_block = "\n\n".join(guidance_sections)

    return (
        f"=== CAPABILITY: {command} ===\n\n"
        f"You are executing the /{command} capability. "
        f"Follow the instructions below precisely.\n"
        f"Do NOT read the guidance files yourself — "
        f"their full content is included below.\n\n"
        f"## Skill Instructions\n\n"
        f"{skill_content}\n\n"
        f"{guidance_block}\n\n"
        f"=== USER REQUEST ===\n"
        f"/{command} {args}"
    )
