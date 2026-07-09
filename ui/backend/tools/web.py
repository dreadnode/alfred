"""Web tools — fetch pages and search the web."""

import html as html_mod
import os
import re
import typing as t

import aiohttp

from dreadnode.agent.tools import AnyTool, tool

_MAX_RESPONSE_BYTES: int = 2 * 1024 * 1024  # 2 MB cap on response body
_USER_AGENT: str = "agentic-latex/0.1 (research-agent; +https://github.com)"
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


def make_web_search(search_api_key_env: str | None) -> AnyTool:
    """Create a web search tool that closes over the API key env var.

    Args:
        search_api_key_env: Name of the env-var holding the Tavily API key,
            or ``None`` if web search is not configured.

    Returns:
        A ``web_search`` tool object.
    """
    api_key: str = ""
    if search_api_key_env:
        api_key = os.environ.get(search_api_key_env, "")

    @tool(catch=True)
    async def web_search(
        query: t.Annotated[str, "Search query"],
        max_results: t.Annotated[int, "Maximum number of results"] = 10,
    ) -> str:
        """Search the web and return a list of results with titles, URLs, and snippets.

        Uses the Tavily search API. If no API key is configured, returns a message
        suggesting ``search_citations`` for academic papers instead.
        """
        if not api_key:
            return (
                "Web search is not configured (no search API key provided). "
                "Use search_citations for academic paper search via Semantic Scholar, "
                "or use web_fetch if you already have a URL."
            )

        async with aiohttp.ClientSession() as session:
            payload = {
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            }
            async with session.post(
                "https://api.tavily.com/search",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        results: list[dict[str, t.Any]] = data.get("results", [])
        if not results:
            return f"No results found for: {query}"

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            result_url = r.get("url", "")
            snippet = r.get("content", "")[:200]
            lines.append(f"{i}. {title}\n   {result_url}\n   {snippet}")

        return "\n\n".join(lines)

    return web_search
