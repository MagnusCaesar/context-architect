#!/usr/bin/env python3
"""Close a context task: release lock, validate, regenerate docs."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from context_utils import (
    agent_role,
    append_ledger_event,
    context_mutex,
    find_context_root,
    has_permission,
    now_utc,
    permission_denied,
    read_meta,
    remove_active_lock,
    resolve_context_page,
    set_meta_in_content,
    validation_failure_summary,
    write_atomic,
)


def release_lock(context_root: Path, page: str, agent_id: str) -> dict:
    with context_mutex(context_root, f"lock-{page}"):
        return _release_lock(context_root, page, agent_id)


def _release_lock(context_root: Path, page: str, agent_id: str) -> dict:
    if not has_permission(context_root, agent_id, "release_lock"):
        return permission_denied(agent_id, "release_lock", agent_role(context_root, agent_id))

    page_path = resolve_context_page(context_root, page)
    if not page_path.exists():
        result = {"status": "release_denied_wrong_owner", "released": False, "reason": f"{page} does not exist"}
        append_ledger_event(context_root, "release", page, agent_id, result["status"], result["reason"])
        return result

    current_lock = read_meta(page_path, "locked")
    if current_lock != "true":
        result = {"status": "released", "released": True, "reason": "was not locked"}
        append_ledger_event(context_root, "release", page, agent_id, result["status"], result["reason"])
        return result

    locked_by = read_meta(page_path, "locked-by")
    forced = False
    if locked_by and locked_by != agent_id:
        if not has_permission(context_root, agent_id, "force_release_lock"):
            result = {
                "status": "release_denied_wrong_owner",
                "released": False,
                "reason": f"locked by {locked_by}, not {agent_id}",
            }
            append_ledger_event(context_root, "release", page, agent_id, result["status"], result["reason"])
            return result
        forced = True

    content = page_path.read_text(errors="replace")
    content = set_meta_in_content(content, "locked", "false")
    content = set_meta_in_content(content, "locked-by", "")
    content = set_meta_in_content(content, "locked-at", "")
    content = set_meta_in_content(content, "updated", now_utc()[:10])
    content = set_meta_in_content(content, "reviewed-at", now_utc())
    write_atomic(page_path, content, context_root=context_root)
    remove_active_lock(context_root, page, locked_by if forced else agent_id)

    result = {"status": "released", "released": True, "forced": forced}
    details = f"forced release previous_owner={locked_by}" if forced else "lock released"
    append_ledger_event(context_root, "release", page, agent_id, result["status"], details)
    return result


def run_validate(context_root: Path) -> dict:
    validate_script = context_root / "scripts" / "validate.py"
    if not validate_script.exists():
        validate_script = context_root / "validate.py"
    if not validate_script.exists():
        return {"ran": False, "reason": "validate.py not found"}
    try:
        result = subprocess.run(
            [sys.executable, str(validate_script)],
            capture_output=True,
            text=True,
            cwd=str(context_root.parent),
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"ran": True, "passed": False, "output": "timeout", "failures": ["timeout"]}
    except Exception as e:
        return {"ran": False, "reason": str(e)}

    output = result.stdout.strip()
    passed = result.returncode == 0
    return {
        "ran": True,
        "passed": passed,
        "output": output[-1000:] if output else "",
        "errors": result.stderr.strip()[-300:] if result.stderr else "",
        "failures": validation_failure_summary(output) if not passed else [],
    }


def run_generate_docs(context_root: Path) -> dict:
    gen_script = context_root / "scripts" / "generate-docs.py"
    if not gen_script.exists():
        gen_script = context_root / "generate-docs.py"
    if not gen_script.exists():
        return {"ran": False, "reason": "generate-docs.py not found"}
    try:
        result = subprocess.run(
            [sys.executable, str(gen_script)],
            capture_output=True,
            text=True,
            cwd=str(context_root.parent),
            timeout=30,
        )
        return {
            "ran": True,
            "success": result.returncode == 0,
            "output": result.stdout.strip() if result.stdout else "",
        }
    except subprocess.TimeoutExpired:
        return {"ran": True, "success": False, "output": "timeout"}
    except Exception as e:
        return {"ran": False, "reason": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Close a context task")
    parser.add_argument("--page", required=True, help="Target page (e.g., parser.html)")
    parser.add_argument("--summary", required=True, help="What changed")
    parser.add_argument("--agent-id", default=os.environ.get("AGENT_ID", "orchestrator"))
    parser.add_argument("--skip-validate", action="store_true", help="Skip validation step")
    parser.add_argument("--skip-docs", action="store_true", help="Skip doc regeneration")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"status": "error", "error": "No context/ directory found"}))
        sys.exit(1)

    try:
        page_path = resolve_context_page(context_root, args.page, must_exist=True)
        page = page_path.relative_to(context_root).as_posix()
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)

    validate_result = {"ran": False, "reason": "skipped"}
    if not args.skip_validate:
        validate_result = run_validate(context_root)

    if not validate_result.get("passed", True):
        status = "validation_warning"
        instruction = "Validation failed. Lock kept so the owner can repair listed failures."
        append_ledger_event(
            context_root,
            "close_validation",
            page,
            args.agent_id,
            status,
            "; ".join(validate_result.get("failures", [])[:3]),
        )
        result = {
            "status": status,
            "page": page,
            "summary": args.summary,
            "lock_released": {"ran": False, "released": False, "reason": "validation failed"},
            "validation": validate_result,
            "docs_generated": {"ran": False, "reason": "validation failed"},
            "instruction": instruction,
        }
        print(json.dumps(result, indent=2))
        return

    lock_result = release_lock(context_root, page, args.agent_id)

    docs_result = {"ran": False, "reason": "skipped"}
    if lock_result.get("released") and not args.skip_docs:
        docs_result = run_generate_docs(context_root)

    if not lock_result.get("released"):
        status = lock_result.get("status", "release_denied_wrong_owner")
        instruction = f"Lock release failed: {lock_result.get('reason')}"
    else:
        status = "released"
        instruction = "Task closed."

    result = {
        "status": status,
        "page": page,
        "summary": args.summary,
        "lock_released": lock_result,
        "validation": validate_result,
        "docs_generated": docs_result,
        "instruction": instruction,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
