#!/usr/bin/env python3
"""Search for academic papers and add citations to bibliography.bib.

Uses the Semantic Scholar API to search for papers and retrieve BibTeX
entries. Works without an API key (100 req/5min), or set S2_API_KEY
for higher limits (1000 req/min). A differently named environment variable can
be selected with ``--api-key-env``.

Get a free key at: https://www.semanticscholar.org/product/api

Usage:
    python3 scripts/cite.py search "transformer attention mechanism"
    python3 scripts/cite.py add <paper-id>
    python3 scripts/cite.py search --add "BERT pre-training"
    S2_API_KEY=xxx python3 scripts/cite.py search "deep learning"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from credentials import read_secret_from_env

S2_API = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "paperId,title,authors,year,venue,externalIds,citationCount,url"

# API key: set via S2_API_KEY or select another environment variable with
# --api-key-env. Raw secrets are never accepted in process arguments.
# Free keys available at https://www.semanticscholar.org/product/api
_api_key: str | None = os.environ.get("S2_API_KEY")


def _api_get(url: str) -> dict[str, Any] | None:
    """Make a GET request to the Semantic Scholar API."""
    headers: dict[str, str] = {"User-Agent": "alfred"}
    if _api_key:
        headers["x-api-key"] = _api_key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("  Rate limited — waiting 3s...", file=sys.stderr)
            time.sleep(3)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            except Exception:
                pass
        print(f"  API error: {e.code} {e.reason}", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  Network error: {e}", file=sys.stderr)
        return None


def search_papers(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search Semantic Scholar for papers matching a query."""
    encoded = urllib.parse.quote(query)
    url = f"{S2_API}/paper/search?query={encoded}&limit={limit}&fields={S2_FIELDS}"
    data = _api_get(url)
    if not data:
        return []
    return data.get("data", [])


def get_paper(paper_id: str) -> dict[str, Any] | None:
    """Fetch a single paper by Semantic Scholar ID, DOI, or arXiv ID."""
    url = f"{S2_API}/paper/{paper_id}?fields={S2_FIELDS}"
    return _api_get(url)


def get_bibtex(paper_id: str) -> str | None:
    """Fetch the BibTeX entry for a paper from Semantic Scholar."""
    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
    headers: dict[str, str] = {
        "User-Agent": "alfred",
        "Accept": "application/x-bibtex",
    }
    if _api_key:
        headers["x-api-key"] = _api_key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode().strip()
    except Exception as e:
        print(f"  Could not fetch BibTeX: {e}", file=sys.stderr)
        return None


def _make_cite_key(paper: dict[str, Any]) -> str:
    """Generate a short citation key from first author surname and year."""
    authors = paper.get("authors", [])
    if authors:
        surname = authors[0].get("name", "unknown").split()[-1].lower()
        surname = re.sub(r"[^a-z]", "", surname)
    else:
        surname = "unknown"
    year = paper.get("year", "")
    return f"{surname}{year}"


def _format_result(i: int, paper: dict[str, Any]) -> str:
    """Format a single search result for display."""
    title = paper.get("title", "Untitled")
    authors = paper.get("authors", [])
    author_str = ", ".join(a.get("name", "") for a in authors[:3])
    if len(authors) > 3:
        author_str += " et al."
    year = paper.get("year", "?")
    venue = paper.get("venue", "")
    cites = paper.get("citationCount", 0)
    pid = paper.get("paperId", "")
    venue_str = f" — {venue}" if venue else ""
    return f"  [{i + 1}] {title}\n      {author_str} ({year}){venue_str} [{cites} citations]\n      ID: {pid}"


def _read_bib(bib_path: str) -> str:
    """Read bibliography file contents."""
    if os.path.exists(bib_path):
        with open(bib_path) as f:
            return f.read()
    return ""


def _key_exists(bib_content: str, cite_key: str) -> bool:
    """Check if a citation key already exists in the bib file."""
    return bool(re.search(rf"@\w+\{{{re.escape(cite_key)}\s*,", bib_content))


def _add_bibtex_entry(bib_path: str, bibtex: str, cite_key: str) -> bool:
    """Append a BibTeX entry to the bibliography file.

    Replaces the entry's citation key with the provided one.
    Returns True if the entry was added.
    """
    bib_content = _read_bib(bib_path)

    if _key_exists(bib_content, cite_key):
        print(f"  Key '{cite_key}' already exists in {os.path.basename(bib_path)}")
        return False

    # Replace the key in the bibtex entry
    bibtex_with_key = re.sub(r"(@\w+)\{[^,]*,", rf"\1{{{cite_key},", bibtex, count=1)

    with open(bib_path, "a") as f:
        f.write("\n" + bibtex_with_key + "\n")

    return True


def cmd_search(
    query: str,
    project_root: str,
    *,
    limit: int = 10,
    auto_add: bool = False,
) -> int:
    """Search for papers and optionally add them to bibliography."""
    print(f'Searching: "{query}"\n')

    papers = search_papers(query, limit=limit)
    if not papers:
        print("  No results found.")
        return 0

    for i, paper in enumerate(papers):
        print(_format_result(i, paper))
        print()

    if auto_add and papers:
        paper = papers[0]
        return _add_paper(paper, project_root)

    print("To add a paper: python3 scripts/cite.py add <ID>")
    return 0


def _add_paper(paper: dict[str, Any], project_root: str) -> int:
    """Add a paper's BibTeX to the bibliography file."""
    pid = paper.get("paperId", "")
    title = paper.get("title", "Untitled")
    cite_key = _make_cite_key(paper)
    bib_path = os.path.join(project_root, "bibliography.bib")

    print(f"  Adding: {title}")
    bibtex = get_bibtex(pid)
    if not bibtex:
        return 1

    if _add_bibtex_entry(bib_path, bibtex, cite_key):
        print(f"  Added to bibliography.bib as \\cite{{{cite_key}}}")
    return 0


def cmd_add(paper_id: str, project_root: str) -> int:
    """Fetch a paper by ID and add its BibTeX to bibliography."""
    print(f"Fetching: {paper_id}")
    paper = get_paper(paper_id)
    if not paper:
        print("  Paper not found.", file=sys.stderr)
        return 1

    print(f"  Found: {paper.get('title', 'Untitled')}")
    return _add_paper(paper, project_root)


def main() -> None:
    global _api_key
    if any(
        argument == "--api-key" or argument.startswith("--api-key=")
        for argument in sys.argv[1:]
    ):
        print("Error: invalid command-line arguments", file=sys.stderr)
        sys.exit(2)

    key_help = "Environment variable containing the Semantic Scholar API key"
    root_help = "Project root directory"
    parser = argparse.ArgumentParser(
        description="Search for papers and add citations to bibliography.bib",
    )
    subparsers = parser.add_subparsers(dest="command")

    sp_search = subparsers.add_parser("search", help="Search for papers")
    sp_search.add_argument("query", help="Search query")
    sp_search.add_argument(
        "--limit", type=int, default=10, help="Max results (default: 10)"
    )
    sp_search.add_argument("--add", action="store_true", help="Auto-add top result")
    sp_search.add_argument(
        "--api-key-env",
        dest="api_key_env",
        default=None,
        help=key_help,
    )
    sp_search.add_argument("--project-root", default=None, help=root_help)

    sp_add = subparsers.add_parser("add", help="Add a paper by ID")
    sp_add.add_argument(
        "paper_id",
        help="Semantic Scholar paper ID, DOI, or arXiv ID (e.g., arXiv:2301.00001)",
    )
    sp_add.add_argument(
        "--api-key-env",
        dest="api_key_env",
        default=None,
        help=key_help,
    )
    sp_add.add_argument("--project-root", default=None, help=root_help)

    args = parser.parse_args()

    api_key_env = getattr(args, "api_key_env", None)
    if api_key_env:
        try:
            _api_key = read_secret_from_env(api_key_env)
        except ValueError as exc:
            parser.error(str(exc))

    root = getattr(args, "project_root", None) or os.getcwd()

    if args.command == "search":
        sys.exit(cmd_search(args.query, root, limit=args.limit, auto_add=args.add))
    elif args.command == "add":
        if not os.path.isfile(os.path.join(root, "bibliography.bib")):
            print(
                "ERROR: bibliography.bib not found. Run from a paper directory or pass --project-root.",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.exit(cmd_add(args.paper_id, root))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
