#!/usr/bin/env python3
"""Route changed files to context pages using page-local tracks metadata."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from context_utils import (
    find_context_root,
    ignored,
    match_tracks,
    read_config,
    repo_root,
    stale_tracks,
    tracks_status,
)


def changed_files_from_git(root: Path, from_ref: str, to_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", from_ref, to_ref],
        capture_output=True,
        text=True,
        cwd=str(root),
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def route_files(context_root: Path, files: list[str]) -> dict:
    config = read_config(context_root)
    root = repo_root(context_root)
    ignore_patterns = config.get("ignoreTracks", [])
    files = [f for f in files if not ignored(f, ignore_patterns)]

    matched_pages = []
    affected_decisions = []
    stale = []
    unmatched = set(files)
    untracked_pages = []

    for page_path in sorted(context_root.rglob("*.html")):
        if "archived" in page_path.parts or "docs" in page_path.parts:
            continue
        if page_path.name == "index.html":
            continue
        page_name = page_path.relative_to(context_root).as_posix()
        tracking = tracks_status(page_path)
        if tracking["status"] == "untracked":
            untracked_pages.append(page_name)
            continue
        if tracking["status"] in ("context-only", "malformed"):
            continue
        page_stale = stale_tracks(tracking["tracks"], root, ignore_patterns)
        if page_stale:
            stale.append({"page": page_name, "tracks": page_stale})
        matches = match_tracks(files, tracking["tracks"])
        if matches:
            matched_pages.append({
                "page": page_name,
                "matched_files": matches,
                "tracks": tracking["tracks"],
            })
            unmatched.difference_update(matches)
        content = page_path.read_text(errors="replace")
        for attrs, _body in re.findall(r'<article\b([^>]*)>(.*?)</article>', content, flags=re.S):
            if not re.search(r'class="[^"]*\bdecision\b[^"]*"', attrs):
                continue
            m = re.search(r'data-tracks="([^"]*)"', attrs)
            if not m:
                continue
            decision_tracks = [part.strip() for part in m.group(1).split(",") if part.strip()]
            decision_matches = match_tracks(files, decision_tracks)
            if decision_matches:
                id_match = re.search(r'id="([^"]+)"', attrs)
                affected_decisions.append({
                    "page": page_name,
                    "decision": id_match.group(1) if id_match else "",
                    "matched_files": decision_matches,
                    "tracks": decision_tracks,
                })

    return {
        "matched_pages": matched_pages,
        "affected_decisions": affected_decisions,
        "unmatched_files": sorted(unmatched),
        "stale_tracks": stale,
        "untracked_pages": untracked_pages,
    }


def main():
    parser = argparse.ArgumentParser(description="Route changed files to context pages")
    parser.add_argument("--files", nargs="*", help="Changed files, repo-root relative")
    parser.add_argument("--from", dest="from_ref", help="Git diff start ref")
    parser.add_argument("--to", dest="to_ref", default="HEAD", help="Git diff end ref")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"status": "error", "error": "No context/ directory found"}))
        sys.exit(1)

    root = repo_root(context_root)
    files = args.files or []
    if args.from_ref:
        try:
            files.extend(changed_files_from_git(root, args.from_ref, args.to_ref))
        except RuntimeError as e:
            print(json.dumps({"status": "error", "error": str(e)}))
            sys.exit(1)
    if not files:
        print(json.dumps({"status": "error", "error": "provide --files or --from"}, indent=2))
        sys.exit(1)
    print(json.dumps(route_files(context_root, sorted(set(files))), indent=2))


if __name__ == "__main__":
    main()
