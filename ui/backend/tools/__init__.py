"""Agent tools for the ALFRED web UI."""

from .latex import make_latex_tools
from .web import web_fetch, web_search

__all__ = [
    "make_latex_tools",
    "web_fetch",
    "web_search",
]
