"""Agent tools for the agentic-latex web UI."""

from .latex import make_latex_tools
from .web import make_web_search, web_fetch

__all__ = [
    "make_latex_tools",
    "make_web_search",
    "web_fetch",
]
