#!/usr/bin/env python3
"""Auto-release locks for pages included in a git commit.

Called by context/.git/hooks/post-commit. Releases all locks for committed
HTML pages, runs validation once, regenerates docs once.

Always exits 0 — must never block git commit.
"""

import subprocess
import sys
from pathlib import Path

from context_utils import (
    append_ledger_event,
    clear_intents_for_page,
    context_mutex,
    find_context_root,
    now_utc,
    read_config,
    read_meta,
    remove_active_lock,
    remove_pid_sentinel,
    resolve_context_page,
    set_meta_in_content,
    validation_failure_summary,
    write_atomic,
)


def get_committed_files(context_root: Path) -> list[str]:
    """Get files changed in the most recent commit, as context-root-relative paths.

    Handles both repo layouts: when the repo toplevel IS the context dir
    (project layout) git reports bare paths; when the toplevel is the PARENT
    (firstmate-home layout) git reports paths prefixed with the context dir
    name (e.g. 'context/foo.html'). We strip that prefix so callers always see
    context-root-relative paths.
    """
    try:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            capture_output=True, text=True, cwd=str(context_root), timeout=5,
        )
        if result.returncode != 0:
            return []
        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=str(context_root), timeout=5,
        )
        if top.returncode == 0:
            top_path = Path(top.stdout.strip()).resolve()
            cr = context_root.resolve()
            if cr != top_path and top_path in cr.parents:
                prefix = cr.relative_to(top_path).as_posix() + "/"
                files = [f[len(prefix):] if f.startswith(prefix) else f for f in files]
        return files
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def release_page_lock(context_root: Path, page: str, agent: str) -> bool:
    """Release a single page lock. Returns True if actually released."""
    try:
        page_path = resolve_context_page(context_root, page)
    except (ValueError, FileNotFoundError):
        return False

    if not page_path.exists():
        return False

    with context_mutex(context_root, f"lock-{page}"):
        if read_meta(page_path, "locked") != "true":
            return False

        content = page_path.read_text(errors="replace")
        content = set_meta_in_content(content, "locked", "false")
        content = set_meta_in_content(content, "locked-by", "")
        content = set_meta_in_content(content, "locked-at", "")
        content = set_meta_in_content(content, "updated", now_utc()[:10])
        content = set_meta_in_content(content, "reviewed-at", now_utc())
        write_atomic(page_path, content, context_root=context_root)
        remove_active_lock(context_root, page, agent)

    remove_pid_sentinel(context_root, page)
    clear_intents_for_page(context_root, page)
    append_ledger_event(
        context_root, "auto_release", page, "system",
        "released_on_commit", f"previous_owner={agent}",
        trigger_hygiene=False,
    )
    return True


def run_validate(context_root: Path) -> dict:
    """Run validate.py non-blocking."""
    validate_script = context_root / "scripts" / "validate.py"
    if not validate_script.exists():
        return {"ran": False}
    try:
        result = subprocess.run(
            [sys.executable, str(validate_script)],
            capture_output=True, text=True,
            cwd=str(context_root.parent), timeout=30,
        )
        return {
            "ran": True,
            "passed": result.returncode == 0,
            "failures": validation_failure_summary(result.stdout) if result.returncode != 0 else [],
        }
    except (subprocess.TimeoutExpired, OSError):
        return {"ran": True, "passed": False, "failures": ["timeout"]}


def run_generate_docs(context_root: Path) -> bool:
    """Run generate-docs.py non-blocking."""
    gen_script = context_root / "scripts" / "generate-docs.py"
    if not gen_script.exists():
        gen_script = context_root / "generate-docs.py"
    if not gen_script.exists():
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(gen_script)],
            capture_output=True, text=True,
            cwd=str(context_root.parent), timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def main():
    try:
        context_root = find_context_root()
        if not context_root:
            sys.exit(0)

        config = read_config(context_root)
        if not config.get("autoReleaseOnCommit", True):
            sys.exit(0)

        committed = get_committed_files(context_root)
        if not committed:
            sys.exit(0)

        released = []
        for filename in committed:
            if not filename.endswith(".html"):
                continue
            if filename == "index.html":
                continue

            try:
                page_path = resolve_context_page(context_root, filename)
            except (ValueError, FileNotFoundError):
                continue

            if not page_path.exists():
                continue

            locked_by = read_meta(page_path, "locked-by")
            if read_meta(page_path, "locked") == "true":
                if release_page_lock(context_root, filename, locked_by or "unknown"):
                    released.append(filename)
                    print(f"[auto-release] Released lock: {filename}", file=sys.stderr)

        if released:
            validation = run_validate(context_root)
            if validation.get("ran") and not validation.get("passed"):
                failures = "; ".join(validation.get("failures", [])[:3])
                print(f"[auto-release] Validation warnings: {failures}", file=sys.stderr)

            run_generate_docs(context_root)

    except Exception as e:
        print(f"[auto-release] Error (non-blocking): {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
