"""Web tools — fetch pages and search the web.

Search fallback chain: Tavily → Brave → DuckDuckGo.
"""

import asyncio
import html as html_mod
import logging
import os
import re
import typing as t

import aiohttp
from dreadnode.agent.tools import tool
from duckduckgo_search import DDGS

log = logging.getLogger(__name__)

_tavily_client: t.Any | None = None
_tavily_unavailable: bool = False

_MAX_CONTENT_CHARS: int = 10_000


def _get_tavily_client() -> t.Any | None:
    """Return a cached AsyncTavilyClient if TAVILY_API_KEY is set."""
    global _tavily_client, _tavily_unavailable
    if _tavily_client is not None:
        return _tavily_client
    if _tavily_unavailable:
        return None
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None
    try:
        from tavily import AsyncTavilyClient  # pyright: ignore[reportMissingImports]

        _tavily_client = AsyncTavilyClient(api_key=api_key)
        return _tavily_client
    except ImportError:
        log.warning("tavily-python not installed, falling back to next search backend")
        _tavily_unavailable = True
        return None


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
    async with (
        aiohttp.ClientSession(headers=headers) as session,
        session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp,
    ):
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


def _format_result(
    index: int,
    title: str,
    url: str,
    snippet: str,
    score: float | None = None,
    content: str | None = None,
) -> str:
    """Format a single search result consistently across backends."""
    header = f"{index}. {title}"
    if score is not None:
        header += f" (score: {score:.2f})"
    parts = [header, f"   {url}", f"   {snippet[:200]}"]
    if content:
        truncated = content[:_MAX_CONTENT_CHARS]
        if len(content) > _MAX_CONTENT_CHARS:
            truncated += "\n\n[truncated]"
        parts.append(f"\n   --- Content ---\n{truncated}")
    return "\n".join(parts)


async def _search_tavily(
    query: str, max_results: int, include_content: bool = False
) -> str | None:
    """Search via Tavily. Returns formatted results or None on failure."""
    client = _get_tavily_client()
    if client is None:
        return None

    effective_max = min(max_results, 5) if include_content else max_results
    kwargs: dict[str, t.Any] = {
        "max_results": effective_max,
        "search_depth": "advanced",
    }
    if include_content:
        kwargs["include_raw_content"] = "markdown"

    try:
        resp = await client.search(query, **kwargs)
    except Exception as e:
        log.warning("Tavily search failed, falling back to next backend: %s", e)
        return None

    results = resp.get("results", [])
    if not results:
        return None

    lines: list[str] = ["[Tavily]"]
    for i, r in enumerate(results, 1):
        raw = r.get("raw_content") if include_content else None
        lines.append(
            _format_result(
                i,
                r.get("title", "Untitled"),
                r.get("url", ""),
                r.get("content", ""),
                score=r.get("score"),
                content=raw,
            )
        )
    return "\n\n".join(lines)


async def _search_brave(query: str, max_results: int) -> str | None:
    """Search via Brave Search API. Returns formatted results or None."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return None
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": query,
        "count": min(max_results, 20),
        "text_decorations": "false",
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except Exception as e:
        log.warning("Brave search failed, falling back to next backend: %s", e)
        return None

    results = data.get("web", {}).get("results", [])
    if not results:
        return None

    lines: list[str] = ["[Brave]"]
    for i, r in enumerate(results, 1):
        lines.append(
            _format_result(
                i,
                r.get("title", "Untitled"),
                r.get("url", ""),
                r.get("description", ""),
            )
        )
    return "\n\n".join(lines)


async def _search_ddg(query: str, max_results: int) -> str | None:
    """Search via DuckDuckGo. Returns formatted results or None."""
    results = await asyncio.to_thread(
        lambda: list(DDGS().text(query, max_results=max_results))
    )
    if not results:
        return None

    lines: list[str] = ["[DuckDuckGo]"]
    for i, r in enumerate(results, 1):
        lines.append(
            _format_result(
                i,
                r.get("title", "Untitled"),
                r.get("href", ""),
                r.get("body", ""),
            )
        )
    return "\n\n".join(lines)


@tool(catch=True)
async def web_search(
    query: t.Annotated[str, "Search query"],
    max_results: t.Annotated[int, "Maximum number of results"] = 10,
    include_content: t.Annotated[
        bool,
        "When True, include full page content inline with each result "
        "(Tavily only — saves follow-up web_fetch calls). "
        "Results are capped at 5 and page text is truncated to ~10k chars each.",
    ] = False,
) -> str:
    """Search the web and return results with titles, URLs, and snippets.

    Uses Tavily (TAVILY_API_KEY), Brave Search (BRAVE_API_KEY), or
    DuckDuckGo as fallbacks. Set include_content=True for research
    workflows where you need full page text without separate web_fetch calls.
    """
    result = await _search_tavily(query, max_results, include_content)
    if result is not None:
        return result

    result = await _search_brave(query, max_results)
    if result is not None:
        return result

    result = await _search_ddg(query, max_results)
    if result is not None:
        return result

    return f"No results found for: {query}"
