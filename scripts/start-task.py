#!/usr/bin/env python3
"""
Start a context task: classify, check staleness, acquire lock if needed.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from context_utils import (
    add_active_lock,
    append_ledger_event,
    find_context_root,
    match_tracks,
    parse_tracks,
    read_config,
    read_meta,
    remove_active_lock,
    repo_root,
    set_meta_in_content,
    stale_tracks,
    tracks_status,
    write_atomic,
)


def classify_task(lines_changed: int, files_changed: int) -> str:
    if lines_changed == 0:
        return "read-only"
    if lines_changed <= 5 and files_changed <= 2:
        return "tiny-write"
    return "standard-write"


def page_review_time(page_path: Path) -> str:
    return read_meta(page_path, "reviewed-at") or read_meta(page_path, "updated")


def check_staleness(context_root: Path, page: str) -> dict:
    page_path = context_root / page
    if not page_path.exists():
        return {"status": "untracked", "stale": False, "reason": "page does not exist yet"}

    tracking = tracks_status(page_path)
    if tracking["status"] == "untracked":
        return {"status": "untracked", "stale": False, "reason": "no tracks meta"}
    if tracking["status"] == "context-only":
        return {"status": "fresh", "stale": False, "reason": "context-only"}
    if tracking["status"] == "malformed":
        return {"status": "stale", "stale": True, "reason": tracking["reason"]}

    config = read_config(context_root)
    root = repo_root(context_root)
    ignore_patterns = config.get("ignoreTracks", [])
    missing = stale_tracks(tracking["tracks"], root, ignore_patterns)
    reviewed = page_review_time(page_path)
    if not reviewed:
        return {"status": "stale", "stale": True, "reason": "no reviewed-at or updated timestamp", "stale_tracks": missing}

    total = 0
    touched = []
    for track in tracking["tracks"]:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"--since={reviewed}", "--", track],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            count = len(result.stdout.strip().splitlines())
            total += count
            touched.append({"track": track, "commits": count})

    stale = bool(total or missing)
    return {
        "status": "stale" if stale else "fresh",
        "stale": stale,
        "reviewed_at": reviewed,
        "commits_since": total,
        "tracks": tracking["tracks"],
        "touched_tracks": touched,
        "stale_tracks": missing,
    }


def update_lock_meta(context_root: Path, page_path: Path, agent_id: str) -> None:
    content = page_path.read_text(errors="replace")
    now = datetime.now(timezone.utc).isoformat()
    content = set_meta_in_content(content, "locked", "true")
    content = set_meta_in_content(content, "locked-by", agent_id)
    content = set_meta_in_content(content, "locked-at", now)
    write_atomic(page_path, content, context_root=context_root)


def lock_age_minutes(locked_at: str) -> float | None:
    if not locked_at:
        return None
    try:
        lock_time = datetime.fromisoformat(locked_at.replace("Z", "+00:00"))
        if lock_time.tzinfo is None:
            lock_time = lock_time.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - lock_time).total_seconds() / 60


def acquire_lock(context_root: Path, page: str, agent_id: str) -> dict:
    page_path = context_root / page
    if not page_path.exists():
        result = {
            "status": "blocked_active_lock",
            "acquired": False,
            "reason": f"{page} does not exist",
            "action": "orchestrator_resolution_required",
        }
        append_ledger_event(context_root, "acquire", page, agent_id, result["status"], result["reason"])
        return result

    current_lock = read_meta(page_path, "locked")
    if current_lock == "true":
        locked_by = read_meta(page_path, "locked-by")
        locked_at = read_meta(page_path, "locked-at")
        config = read_config(context_root)
        stale_after = int(config.get("staleLockMinutes", 30))
        age = lock_age_minutes(locked_at)
        if age is not None and age > stale_after:
            update_lock_meta(context_root, page_path, agent_id)
            remove_active_lock(context_root, page, locked_by)
            add_active_lock(context_root, page, agent_id)
            result = {
                "status": "broke_stale_lock",
                "acquired": True,
                "broke_stale": True,
                "previous_owner": locked_by,
            }
            append_ledger_event(context_root, "acquire", page, agent_id, result["status"], f"previous_owner={locked_by}")
            return result

        result = {
            "status": "blocked_active_lock",
            "acquired": False,
            "reason": f"locked by {locked_by} since {locked_at}",
            "action": "orchestrator_resolution_required",
        }
        append_ledger_event(context_root, "acquire", page, agent_id, result["status"], result["reason"])
        return result

    update_lock_meta(context_root, page_path, agent_id)
    add_active_lock(context_root, page, agent_id)
    result = {"status": "acquired", "acquired": True}
    append_ledger_event(context_root, "acquire", page, agent_id, result["status"], "lock acquired")
    return result


def main():
    parser = argparse.ArgumentParser(description="Start a context task")
    parser.add_argument("--page", help="Target page (e.g., parser.html)")
    parser.add_argument("--intent", default="", help="What you're doing")
    parser.add_argument("--lines", type=int, default=10, help="Estimated lines changed")
    parser.add_argument("--files", type=int, default=1, help="Estimated files changed")
    parser.add_argument("--agent-id", default=os.environ.get("AGENT_ID", "orchestrator"))
    parser.add_argument("--read-only", action="store_true", help="Read-only task, no locks")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"error": "No context/ directory found"}))
        sys.exit(1)

    if args.read_only:
        print(json.dumps({
            "status": "read_only",
            "task_class": "read-only",
            "lock_status": "not needed",
            "instruction": "Proceed. No locks required for reads.",
        }, indent=2))
        return

    if not args.page:
        print(json.dumps({"error": "--page required for write tasks"}))
        sys.exit(1)

    task_class = classify_task(args.lines, args.files)
    staleness = check_staleness(context_root, args.page)
    lock_status = acquire_lock(context_root, args.page, args.agent_id)

    result = {
        "status": lock_status.get("status"),
        "task_class": task_class,
        "page": args.page,
        "intent": args.intent,
        "lock_status": lock_status,
        "staleness": staleness,
        "instruction": "",
    }

    if lock_status.get("acquired"):
        if staleness.get("stale"):
            result["instruction"] = f"Lock acquired. WARNING: page may be stale: {staleness.get('reason', staleness.get('status'))}."
        else:
            result["instruction"] = "Lock acquired. Proceed with edit."
    else:
        result["instruction"] = f"BLOCKED: {lock_status.get('reason', 'unknown')}. {lock_status.get('action', '')}"

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
