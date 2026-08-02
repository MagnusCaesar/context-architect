#!/usr/bin/env python3
"""Check context page freshness using page-local tracks metadata."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from context_utils import (
    find_context_root,
    read_config,
    read_meta,
    resolve_context_page,
    repo_root,
    stale_tracks,
    tracks_status,
)


def review_time(page_path: Path) -> str:
    return read_meta(page_path, "reviewed-at") or read_meta(page_path, "updated")


def check_freshness_single(context_root: Path, page: str, root: Path, ignore_patterns: list[str]) -> dict:
    try:
        page_path = resolve_context_page(context_root, page)
        page = page_path.relative_to(context_root).as_posix()
    except ValueError as e:
        return {"page": page, "exists": False, "status": "error", "reason": str(e)}
    if not page_path.exists():
        return {"page": page, "exists": False, "status": "untracked", "reason": "page does not exist"}

    tracking = tracks_status(page_path)
    if tracking["status"] == "untracked":
        return {"page": page, "exists": True, "status": "untracked", "stale": False, "reason": "missing tracks meta"}
    if tracking["status"] == "context-only":
        return {"page": page, "exists": True, "status": "fresh", "stale": False, "tracks": tracking["tracks"], "reason": "context-only"}
    if tracking["status"] == "malformed":
        return {"page": page, "exists": True, "status": "stale", "stale": True, "reason": tracking["reason"], "tracks": tracking["tracks"]}

    reviewed = review_time(page_path)
    missing_tracks = stale_tracks(tracking["tracks"], root, ignore_patterns)
    if not reviewed:
        return {
            "page": page,
            "exists": True,
            "status": "stale",
            "stale": True,
            "reason": "missing reviewed-at or updated meta",
            "tracks": tracking["tracks"],
            "stale_tracks": missing_tracks,
        }

    total = 0
    touched = []
    git_errors = []
    for track in tracking["tracks"]:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"--since={reviewed}", "--", track],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            git_errors.append({"track": track, "error": "git log timed out"})
            continue
        except (FileNotFoundError, OSError) as e:
            git_errors.append({"track": track, "error": str(e)})
            continue
        if result.returncode != 0:
            git_errors.append({"track": track, "error": result.stderr.strip() or f"git exited {result.returncode}"})
            continue
        if result.returncode == 0 and result.stdout.strip():
            commits = len(result.stdout.strip().splitlines())
            total += commits
            touched.append({"track": track, "commits": commits})

    if git_errors:
        return {
            "page": page,
            "exists": True,
            "status": "unknown",
            "stale": None,
            "reviewed_at": reviewed,
            "tracks": tracking["tracks"],
            "git_errors": git_errors,
            "stale_tracks": missing_tracks,
        }

    stale = bool(total or missing_tracks)
    return {
        "page": page,
        "exists": True,
        "status": "stale" if stale else "fresh",
        "stale": stale,
        "reviewed_at": reviewed,
        "tracks": tracking["tracks"],
        "commits_since": total,
        "touched_tracks": touched,
        "stale_tracks": missing_tracks,
    }


def check_vendored_drift(context_root, current_commits):
    """Warn when a page's recorded vendored-commit differs from the current
    upstream commit. current_commits maps vendored-source -> commit sha.
    ponytail: caller resolves upstream shas (git -C upstream rev-parse); this
    fn only compares, so it stays testable without a real upstream checkout."""
    warns = []
    for page in sorted(context_root.rglob("*.html")):
        content = page.read_text(errors="replace")
        m_commit = re.search(r'<meta name="vendored-commit" content="([^"]*)"', content)
        m_src = re.search(r'<meta name="vendored-source" content="([^"]*)"', content)
        if not (m_commit and m_src):
            continue
        recorded, src = m_commit.group(1), m_src.group(1)
        current = current_commits.get(src)
        if current and current != recorded:
            warns.append(f"{page.name}: vendored DRIFT {src} recorded={recorded} current={current}")
    return warns


def main():
    parser = argparse.ArgumentParser(description="Check context page freshness")
    parser.add_argument("--page", help="Check specific page only")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"status": "error", "error": "No context/ directory found"}))
        sys.exit(1)

    config = read_config(context_root)
    root = repo_root(context_root)
    ignore_patterns = config.get("ignoreTracks", [])

    pages = [args.page] if args.page else sorted(
        f.relative_to(context_root).as_posix() for f in context_root.rglob("*.html") if f.name != "index.html" and "archived" not in f.parts and "docs" not in f.parts
    )
    results = [check_freshness_single(context_root, page, root, ignore_patterns) for page in pages]

    if args.json:
        print(json.dumps(results, indent=2))
        return

    grouped = {"stale": [], "fresh": [], "untracked": [], "unknown": [], "error": []}
    for item in results:
        grouped.setdefault(item.get("status", "untracked"), []).append(item)

    for status in ["stale", "unknown", "error", "untracked", "fresh"]:
        entries = grouped.get(status, [])
        if not entries:
            continue
        print(f"{status.upper()} ({len(entries)} pages):")
        for entry in entries:
            detail = entry.get("reason") or f"reviewed {entry.get('reviewed_at', 'unknown')}"
            print(f"  {entry['page']}: {detail}")


if __name__ == "__main__":
    main()
