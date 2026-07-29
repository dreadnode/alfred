"""Web tools — fetch pages and search the web."""

import asyncio
import html as html_mod
import re
import typing as t

import aiohttp
from duckduckgo_search import DDGS

from dreadnode.agent.tools import tool

_MAX_RESPONSE_BYTES: int = 2 * 1024 * 1024  # 2 MB cap on response body
_USER_AGENT: str = "alfred (research-agent; +https://github.com)"
_TEXT_PREFIXES: tuple[str, ...] = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
)


def _strip_html(raw_html: str) -> str:
    """Strip HTML tags, decode entities, and collapse whitespace.

    Args:
        raw_html: Raw HTML string.

    Returns:
        Plain text with tags removed, entities decoded, and whitespace normalized.
    """
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@tool(catch=True)
async def web_fetch(
    url: t.Annotated[str, "URL to fetch"],
    max_chars: t.Annotated[int, "Maximum characters to return"] = 50000,
) -> str:
    """Fetch a web page and return its text content.

    Strips HTML tags and returns plain text, truncated to *max_chars*.
    Use this to read papers, blog posts, documentation, or any web resource.
    Rejects binary responses (PDFs, images, etc.).
    """
    headers = {"User-Agent": _USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()

            content_type = resp.content_type or ""
            if not content_type.startswith(_TEXT_PREFIXES):
                raise ValueError(
                    f"Non-text content type '{content_type}'. "
                    "web_fetch only supports text, JSON, XML, and XHTML."
                )

            raw = await resp.content.read(_MAX_RESPONSE_BYTES)
            encoding = resp.get_encoding() or "utf-8"
            text = raw.decode(encoding, errors="replace")

    if "html" in content_type:
        text = _strip_html(text)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[truncated]"
    return text


@tool(catch=True)
async def web_search(
    query: t.Annotated[str, "Search query"],
    max_results: t.Annotated[int, "Maximum number of results"] = 10,
) -> str:
    """Search the web and return a list of results with titles, URLs, and snippets.

    Uses DuckDuckGo. No API key required.
    """
    results = await asyncio.to_thread(
        lambda: list(DDGS().text(query, max_results=max_results))
    )

    if not results:
        return f"No results found for: {query}"

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("href", "")
        snippet = r.get("body", "")[:200]
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")

    return "\n\n".join(lines)
