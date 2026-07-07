#!/usr/bin/env python3
"""List and summarize peer review records from reviews/.

Parses YAML frontmatter from review files and displays a summary table
or detailed JSON output.

Usage:
    python3 scripts/reviews.py                    # Summary table
    python3 scripts/reviews.py --json             # JSON output
    python3 scripts/reviews.py --reviewer "Alice"  # Filter by reviewer
    python3 scripts/reviews.py --detail <filename> # Show one review in detail
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from typing import Any


def parse_review(filepath: str) -> dict[str, Any]:
    """Parse a review file, extracting frontmatter and body counts in one pass.

    Returns a dict with frontmatter fields plus internal _file, _path,
    and optionally _live_counts keys.
    """
    with open(filepath) as f:
        content = f.read()

    meta: dict[str, Any] = {}

    # Extract YAML frontmatter
    fm_match = re.match(r"^---\n(.+?)\n---\n", content, re.DOTALL)
    if fm_match:
        try:
            import yaml
        except ImportError:
            print("ERROR: PyYAML required — pip install pyyaml", file=sys.stderr)
            sys.exit(1)
        try:
            parsed = yaml.safe_load(fm_match.group(1))
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            pass

    if not meta:
        meta["_parse_error"] = True

    meta["_file"] = os.path.basename(filepath)
    meta["_path"] = filepath

    # If frontmatter issues are all zeros or missing, count from the body.
    # This handles pre-finalization reviews that have notes recorded but
    # haven't had their frontmatter updated yet.
    fm_issues = meta.get("issues", {})
    if not any(v != 0 for v in fm_issues.values() if isinstance(v, int)):
        body_counts = _count_body_issues(content)
        if any(v != 0 for v in body_counts.values()):
            meta["_live_counts"] = body_counts

    return meta


def _count_body_issues(content: str) -> dict[str, int]:
    """Count issues by severity from the markdown body content."""
    counts = {"major": 0, "minor": 0, "nit": 0, "positive": 0}
    current_severity = None
    for line in content.split("\n"):
        lower = line.lower().strip()
        if lower.startswith("## major"):
            current_severity = "major"
        elif lower.startswith("## minor"):
            current_severity = "minor"
        elif lower.startswith("## nit"):
            current_severity = "nit"
        elif lower.startswith("## strength"):
            current_severity = "positive"
        elif lower.startswith("## ") and current_severity:
            current_severity = None
        elif current_severity and re.match(r"^### R\d+", line):
            counts[current_severity] += 1

    return counts


def load_reviews(
    reviews_dir: str,
    reviewer_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Load all review records from the reviews directory."""
    records = []
    pattern = os.path.join(reviews_dir, "*.md")

    for filepath in sorted(glob.glob(pattern)):
        if os.path.basename(filepath) == ".gitkeep":
            continue

        meta = parse_review(filepath)

        if reviewer_filter:
            reviewer = meta.get("reviewer", "")
            if reviewer_filter.lower() not in reviewer.lower():
                continue

        records.append(meta)

    # Sort by date field (frontmatter). Records with missing/empty dates
    # sort to the end rather than the beginning.
    def sort_key(r: dict[str, Any]) -> tuple[int, str]:
        date = r.get("date", "")
        s = str(date) if date else ""
        # (0, date_str) for records with dates, (1, "") for those without
        return (0, s) if s else (1, "")

    records.sort(key=sort_key)

    return records


def get_issue_counts(record: dict[str, Any]) -> tuple[int, int, int, int, bool]:
    """Get major/minor/nit/positive counts and whether they're from live body parse.

    Returns (major, minor, nit, positive, is_live).
    """
    live = record.get("_live_counts")
    if live:
        return (
            live.get("major", 0), live.get("minor", 0),
            live.get("nit", 0), live.get("positive", 0), True,
        )

    issues = record.get("issues", {})
    return (
        issues.get("major", 0), issues.get("minor", 0),
        issues.get("nit", 0), issues.get("positive", 0), False,
    )


def find_record(records: list[dict[str, Any]], review_id: str) -> dict[str, Any] | None:
    """Find a record by filename substring match."""
    for r in records:
        fname = r.get("_file", "")
        if review_id in fname or fname.startswith(review_id):
            return r
    return None


def print_table(records: list[dict[str, Any]]) -> None:
    """Print a summary table of review records."""
    if not records:
        print("No reviews found.")
        return

    print("=== Peer Review History ===\n")
    header = f"  {'Date':<12s} {'Reviewer':<18s} {'Rec.':<14s} {'Maj':>4s} {'Min':>4s} {'Nit':>4s} {'Pos':>4s}  {'File'}"
    print(header)
    print(f"  {'-' * 12} {'-' * 18} {'-' * 14} {'-' * 4} {'-' * 4} {'-' * 4} {'-' * 4}  {'-' * 20}")

    for r in records:
        date = r.get("date", "?")
        if hasattr(date, "strftime"):
            date = date.strftime("%Y-%m-%d")
        else:
            date = str(date)[:10]

        reviewer = r.get("reviewer", "?")[:18]
        rec = r.get("recommendation", "")
        if not rec:
            rec = "pending"
        rec = str(rec)[:14]

        major, minor, nit, positive, is_live = get_issue_counts(r)
        counts_suffix = " *" if is_live else ""

        filename = r.get("_file", "?")

        print(
            f"  {date:<12s} {reviewer:<18s} {rec:<14s}"
            f" {major:>4d} {minor:>4d} {nit:>4d} {positive:>4d}{counts_suffix}  {filename}"
        )

    print()
    print(f"  Total reviews: {len(records)}")

    if any(r.get("_live_counts") for r in records):
        print("  * counts parsed from body (review not yet finalized)")


def print_detail(record: dict[str, Any]) -> None:
    """Print detailed info for a specific review."""
    print(f"=== Review Detail: {record.get('_file', '?')} ===\n")
    for key, val in record.items():
        if key.startswith("_"):
            continue
        if isinstance(val, dict):
            print(f"  {key}:")
            for k, v in val.items():
                print(f"    {k}: {v}")
        elif isinstance(val, list):
            print(f"  {key}:")
            for item in val:
                print(f"    - {item}")
        else:
            print(f"  {key}: {val}")

    live = record.get("_live_counts")
    if live:
        print(f"\n  Issue counts (from body — not yet finalized):")
        for sev, count in live.items():
            print(f"    {sev}: {count}")


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    """Strip internal keys and merge live counts for JSON output."""
    out: dict[str, Any] = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        out[k] = v

    live = record.get("_live_counts")
    if live:
        out["_finalized"] = False
        out["live_counts"] = live
    else:
        out["_finalized"] = True

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="List and summarize peer reviews")
    parser.add_argument("--project-root", default=None, help="Project root directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--reviewer", default=None, help="Filter by reviewer name")
    parser.add_argument(
        "--detail", default=None, metavar="FILENAME",
        help="Show detail for a specific review (match by filename or substring)",
    )
    args = parser.parse_args()

    root = args.project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reviews_dir = os.path.join(root, "reviews")

    if not os.path.isdir(reviews_dir):
        print("No reviews/ directory found.", file=sys.stderr)
        sys.exit(1)

    records = load_reviews(reviews_dir, reviewer_filter=args.reviewer)

    if args.detail:
        record = find_record(records, args.detail)
        if not record:
            print(f"No review matching '{args.detail}' found.", file=sys.stderr)
            sys.exit(1)
        if args.json:
            import json
            print(json.dumps(clean_record(record), indent=2, default=str))
        else:
            print_detail(record)
    elif args.json:
        import json
        clean = [clean_record(r) for r in records]
        print(json.dumps(clean, indent=2, default=str))
    else:
        print_table(records)


if __name__ == "__main__":
    main()
