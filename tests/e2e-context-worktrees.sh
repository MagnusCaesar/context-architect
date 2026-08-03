#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/contarch-worktrees.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

export CONTARCH_ROOT="$ROOT"
export CONTARCH_TMP="$TMP"
python3 - <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["CONTARCH_ROOT"])
base = Path(os.environ["CONTARCH_TMP"])
main, linked = base / "main", base / "linked"
main.mkdir()

def run(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)

def git(*args, cwd=main):
    return run("git", *args, cwd=cwd).stdout.strip()

git("init", "-b", "main")
git("config", "user.email", "e2e@example.invalid")
git("config", "user.name", "contarch e2e")
git("commit", "--allow-empty", "-m", "base")
run(sys.executable, str(root / "scripts/bootstrap.py"), "--target", str(main), "--platform", "codex")
git("worktree", "add", "-b", "linked", str(linked))

sys.path.insert(0, str(main / "context/scripts"))
from context_utils import canonical_context_root, read_ledger_events, read_meta  # noqa: E402
from task_capsule import restore_capsule  # noqa: E402

main_context = canonical_context_root(main)
linked_context = canonical_context_root(linked)
assert main_context == linked_context == main / "context"

start = main_context / "scripts/start-task.py"
close = main_context / "scripts/close-task.py"
started = json.loads(run(
    sys.executable, str(start), "--page", "wiki.html", "--intent", "Update shared wiki",
    "--result", "One verified shared result", "--path", "src/cache.py",
    "--agent-id", "agent-main", cwd=main,
).stdout)
assert started["status"] in {"acquired", "broke_stale_lock"}
capsule = started["capsule"]
assert len(capsule) <= 4000
for forbidden in ("ledger-events.ndjson", "receipt_id", "mutex", "hygiene", "other-project-secret"):
    assert forbidden not in capsule

blocked = json.loads(run(
    sys.executable, str(start), "--page", "wiki.html", "--intent", "Competing update",
    "--agent-id", "agent-linked", cwd=linked,
).stdout)
assert blocked["status"] == "blocked_active_lock"
assert read_meta(linked_context / "wiki.html", "locked-by") == "agent-main"

receipts = [event for event in read_ledger_events(linked_context) if event.get("event") == "task_capsule"]
assert receipts
receipt_id = receipts[-1]["receipt_id"]
restored, _restored_receipt = restore_capsule(linked_context, receipt_id)
assert restored.text == capsule

router = main_context / "decisions.html"
original = router.read_text()
router.write_text(original.replace(
    "</section>",
    '<a href="decisions/missing.html#dec-missing">pollution</a></section>',
    1,
))
failed = json.loads(run(
    sys.executable, str(close), "--page", "wiki.html", "--summary", "invalid graph",
    "--agent-id", "agent-main", cwd=linked,
).stdout)
assert failed["status"] == "validation_warning"
assert read_meta(main_context / "wiki.html", "locked") == "true"

router.write_text(original)
closed = json.loads(run(
    sys.executable, str(close), "--page", "wiki.html", "--summary", "shared lifecycle verified",
    "--agent-id", "agent-main", cwd=main,
).stdout)
assert closed["status"] == "released"
assert read_meta(linked_context / "wiki.html", "locked") == "false"
history = main_context / "history.html"
assert history.exists() and history.resolve() == (linked_context / "history.html").resolve()
events = read_ledger_events(linked_context)
assert any(event.get("page") == "wiki.html" and event.get("status") == "released" for event in events)

print("e2e context worktrees: PASS (shared root, lock, ledger, receipt, validation repair, history)")
PY
