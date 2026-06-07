#!/usr/bin/env python3
"""Explicit orchestrator repair for page-local tracks metadata."""

import argparse
import json
import os
import sys

from context_utils import (
    agent_role,
    append_ledger_event,
    find_context_root,
    has_permission,
    parse_tracks,
    permission_denied,
    read_meta,
    resolve_context_page,
    set_meta_in_content,
    write_atomic,
)


def main():
    parser = argparse.ArgumentParser(description="Update a page's tracks meta")
    parser.add_argument("--page", required=True, help="Context page, e.g. parser.html")
    parser.add_argument("--add", action="append", default=[], help="Track to add; can be repeated")
    parser.add_argument("--remove", action="append", default=[], help="Track to remove; can be repeated")
    parser.add_argument("--agent-id", default=os.environ.get("AGENT_ID", "orchestrator"))
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"status": "error", "error": "No context/ directory found"}))
        sys.exit(1)
    if not has_permission(context_root, args.agent_id, "update_tracks"):
        print(json.dumps(permission_denied(args.agent_id, "update_tracks", agent_role(context_root, args.agent_id)), indent=2))
        sys.exit(1)
    try:
        page_path = resolve_context_page(context_root, args.page, must_exist=True)
        page = page_path.relative_to(context_root).as_posix()
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)

    tracks = parse_tracks(read_meta(page_path, "tracks"))
    original_tracks = list(tracks)
    if args.add and tracks == ["context-only"] and any(item != "context-only" for item in args.add):
        tracks = []
    tracks = [track for track in tracks if track not in set(args.remove)]
    if "context-only" in args.add:
        tracks = ["context-only"]
        args.add = ["context-only"]
        args.remove = []
    for track in args.add:
        if track not in tracks:
            tracks.append(track)
    if tracks == original_tracks:
        print(json.dumps({
            "status": "unchanged",
            "page": page,
            "tracks": tracks,
        }, indent=2))
        return
    content = page_path.read_text(errors="replace")
    new_tracks = ", ".join(tracks)
    content = set_meta_in_content(content, "tracks", new_tracks)
    write_atomic(page_path, content, context_root=context_root)
    append_ledger_event(
        context_root,
        "track_update",
        page,
        args.agent_id,
        "updated",
        f"add={','.join(args.add)} remove={','.join(args.remove)}",
    )
    print(json.dumps({
        "status": "updated",
        "page": page,
        "tracks": tracks,
    }, indent=2))


if __name__ == "__main__":
    main()
