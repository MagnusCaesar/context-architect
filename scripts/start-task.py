#!/usr/bin/env python3
"""
Start a context task: classify, check staleness, acquire lock if needed.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from context_utils import (
    acquire_page_lock,
    agent_role,
    find_context_root,
    has_permission,
    permission_denied,
    read_config,
    read_meta,
    resolve_context_page,
    repo_root,
    stale_tracks,
    tracks_status,
    write_atomic,
)
from task_capsule import CapsuleError, build_capsule, record_receipt


def classify_task(lines_changed: int, files_changed: int) -> str:
    if lines_changed == 0:
        return "read-only"
    if lines_changed <= 5 and files_changed <= 2:
        return "tiny-write"
    return "standard-write"


def write_task_diagnostics(context_root: Path, payload: dict) -> str:
    directory = context_root / ".diagnostics"
    directory.mkdir(exist_ok=True)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    path = directory / f"task-start-{digest}.json"
    write_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", context_root=context_root)
    return path.relative_to(context_root).as_posix()


def page_review_time(page_path: Path) -> str:
    return read_meta(page_path, "reviewed-at") or read_meta(page_path, "updated")


def check_staleness(context_root: Path, page: str) -> dict:
    page_path = resolve_context_page(context_root, page)
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


def acquire_lock(context_root: Path, page: str, agent_id: str, intent: str = "") -> dict:
    return acquire_page_lock(context_root, page, agent_id, intent)


def main():
    parser = argparse.ArgumentParser(description="Start a context task")
    parser.add_argument("--page", help="Target page (e.g., parser.html)")
    parser.add_argument("--intent", default="", help="What you're doing")
    parser.add_argument("--result", default="", help="Expected task result")
    parser.add_argument("--path", action="append", default=[], help="Allowed or affected repository path")
    parser.add_argument("--session", default=os.environ.get("CODEX_SESSION_ID", ""))
    parser.add_argument("--turn", default=os.environ.get("CODEX_TURN_ID", ""))
    parser.add_argument("--lines", type=int, default=10, help="Estimated lines changed")
    parser.add_argument("--files", type=int, default=1, help="Estimated files changed")
    parser.add_argument("--agent-id", default=os.environ.get("AGENT_ID", "orchestrator"))
    parser.add_argument("--read-only", action="store_true", help="Read-only task, no locks")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"status": "error", "error": "No context/ directory found"}))
        sys.exit(1)

    config = read_config(context_root)
    role = agent_role(context_root, args.agent_id)
    task = {
        "task": args.intent or (f"Read {args.page}" if args.read_only and args.page else "Read project context"),
        "result": args.result or ("Complete the scoped read." if args.read_only else "Complete the scoped update."),
    }
    try:
        capsule = build_capsule(
            context_root,
            task,
            args.path,
            role,
            config.get("taskCapsuleMaxChars", 4000),
        )
    except CapsuleError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        sys.exit(1)

    if args.read_only:
        receipt = record_receipt(context_root, capsule, session=args.session, turn=args.turn)
        diagnostics_file = write_task_diagnostics(context_root, {"mode": "read_only", "receipt": receipt})
        print(json.dumps({
            "status": "read_only",
            "task_class": "read-only",
            "lock_status": "not needed",
            "instruction": "Proceed. No locks required for reads.",
            "capsule": capsule.text,
            "diagnostics_file": diagnostics_file,
        }, indent=2))
        return

    if not args.page:
        print(json.dumps({"status": "error", "error": "--page required for write tasks"}))
        sys.exit(1)

    try:
        page_path = resolve_context_page(context_root, args.page)
        page = page_path.relative_to(context_root).as_posix()
    except ValueError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)

    if not has_permission(context_root, args.agent_id, "acquire_lock"):
        result = permission_denied(args.agent_id, "acquire_lock", agent_role(context_root, args.agent_id))
        print(json.dumps(result, indent=2))
        sys.exit(1)

    task_class = classify_task(args.lines, args.files)
    staleness = check_staleness(context_root, page)
    lock_status = acquire_lock(context_root, page, args.agent_id, args.intent)
    if not lock_status.get("acquired"):
        instruction = f"BLOCKED: {lock_status.get('reason', 'unknown')}. {lock_status.get('action', '')}".strip()
        if lock_status.get("status") == "blocked_active_lock":
            print(json.dumps({
                "status": "blocked_active_lock",
                "page": page,
                "action": lock_status.get("action", "orchestrator_resolution_required"),
                "instruction": instruction,
            }, indent=2))
        else:
            print(json.dumps({
                "status": lock_status.get("status"),
                "page": page,
                "lock_status": lock_status,
                "instruction": instruction,
            }, indent=2))
        return

    receipt = record_receipt(context_root, capsule, session=args.session, turn=args.turn)
    diagnostics_file = write_task_diagnostics(context_root, {
        "lock_status": lock_status,
        "receipt": receipt,
        "staleness": staleness,
    })

    result = {
        "status": lock_status.get("status"),
        "task_class": task_class,
        "page": page,
        "intent": args.intent,
        "lock_status": lock_status,
        "capsule": capsule.text,
        "diagnostics_file": diagnostics_file,
        "instruction": "",
    }

    if staleness.get("stale"):
        result["instruction"] = f"Lock acquired. WARNING: page may be stale: {staleness.get('reason', staleness.get('status'))}."
    else:
        result["instruction"] = "Lock acquired. Proceed with edit."

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
