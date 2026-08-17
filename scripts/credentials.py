"""Helpers for resolving secrets without placing them in process arguments."""

from __future__ import annotations

import os
import re

_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_secret_from_env(name: str) -> str:
    """Return a non-empty secret stored in the named environment variable.

    Args:
        name: Environment variable name supplied through a CLI option.

    Returns:
        The secret stored in the environment variable.

    Raises:
        ValueError: If *name* is not a valid environment variable name or the
            variable is unset or empty.
    """
    if not _ENV_VAR_NAME.fullmatch(name):
        raise ValueError(
            "API keys must be passed through a valid environment variable name"
        )

    value = os.environ.get(name)
    if not value:
        raise ValueError("The API-key environment variable is not set or is empty")
    return value
