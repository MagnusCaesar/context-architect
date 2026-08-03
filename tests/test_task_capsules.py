import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from context_utils import read_ledger_events, write_context_locator  # noqa: E402
from task_capsule import CapsuleError, build_capsule, record_receipt, restore_capsule  # noqa: E402


FORBIDDEN_MODEL_TEXT = (
    "ledger-events.ndjson",
    "mutex",
    "receipt_id",
    "daily_hygiene",
    "project-registry",
    "archived-at",
    "hookSpecificOutput",
)


def make_root(tmp_path: Path, name: str = "project") -> Path:
    project = tmp_path / name
    root = project / "context"
    root.mkdir(parents=True)
    (root / "index.html").write_text("<html><body>context</body></html>")
    (root / "ledger.html").write_text("<html><body><main></main></body></html>")
    (root / "config.json").write_text(json.dumps({
        "repoRoots": [{"path": ".", "label": "main"}],
        "taskCapsuleMaxChars": 4000,
        "taskCapsuleMaxNodes": 8,
    }))
    return root


def write_node(
    root: Path,
    node_id: str,
    kind: str,
    status: str,
    statement: str,
    *,
    affects: str = "src/cache.py",
) -> Path:
    directory = {
        "wiki": "wiki",
        "decision": "decisions",
        "failure": "failure-todos",
        "work": "workstreams",
    }[kind]
    path = root / directory / f"{node_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'''<html><head>
<meta name="contract-version" content="2">
<meta name="node-id" content="{node_id}">
<meta name="kind" content="{kind}">
<meta name="status" content="{status}">
<meta name="affects" content="{affects}">
</head><body><article id="{node_id}" data-statement="{statement}"></article></body></html>''')
    return path


def test_capsule_contains_only_scoped_model_context(tmp_path):
    root = make_root(tmp_path)
    write_node(root, "wiki-cache", "wiki", "active", "Cache is tenant-scoped.")
    write_node(root, "dec-cache", "decision", "accepted", "Cache keys include tenant ID.")
    write_node(root, "fail-cache", "failure", "open", "Cache migration is blocked by old keys.")
    write_node(root, "work-cache", "work", "blocked", "Cache rollout waits for migration.")
    write_node(root, "dec-parser", "decision", "accepted", "Unrelated parser decision", affects="src/parser.py")
    write_node(root, "wiki-private", "wiki", "active", "mutex receipt_id daily_hygiene", affects="src/cache.py")

    capsule = build_capsule(
        root,
        {"task": "Repair cache isolation", "result": "Tenant-safe cache reads"},
        ["src/cache.py"],
        "worker",
    )

    assert "Task: Repair cache isolation" in capsule.text
    assert "Result: Tenant-safe cache reads" in capsule.text
    assert "Scope: src/cache.py" in capsule.text
    assert "Cache is tenant-scoped." in capsule.text
    assert "Cache keys include tenant ID." in capsule.text
    assert "Cache migration is blocked by old keys." in capsule.text
    assert "Cache rollout waits for migration." in capsule.text
    assert "Unrelated parser decision" not in capsule.text
    assert all(term not in capsule.text for term in FORBIDDEN_MODEL_TEXT)
    assert len(capsule.node_ids) == 4
    assert len(capsule.text) <= 4000


def test_capsule_bounds_and_truncation_are_deterministic(tmp_path):
    root = make_root(tmp_path)
    for index in range(12):
        write_node(root, f"wiki-{index:02d}", "wiki", "active", f"Fact {index} " + "x" * 600)
    task = {"task": "T" * 7000, "result": "R" * 7000}

    first = build_capsule(root, task, ["src/cache.py"], "worker")
    second = build_capsule(root, task, ["src/cache.py"], "worker")

    assert first.text == second.text
    assert first.node_ids == second.node_ids
    assert len(first.text) <= 4000
    assert len(first.node_ids) <= 8
    assert first.text.startswith("Task: ")
    assert "\nResult: " in first.text


def test_receipt_hashes_exact_bytes_and_restore_rebuilds_changed_node(tmp_path):
    root = make_root(tmp_path)
    path = write_node(root, "dec-cache", "decision", "accepted", "Use tenant cache keys.")
    capsule = build_capsule(root, {"task": "Cache", "result": "Safe cache"}, ["src/cache.py"], "worker")

    receipt = record_receipt(root, capsule, session="session-1", turn="turn-1")
    stored = read_ledger_events(root)[-1]
    assert stored["node_ids"] == ["dec-cache"]
    assert stored["source_hashes"] == {"dec-cache": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert stored["session"] == "session-1"
    assert stored["turn"] == "turn-1"
    assert stored["budget"] == len(capsule.text)
    assert stored["time"]
    assert "receipt_id" not in capsule.text

    path.write_text(path.read_text().replace("Use tenant cache keys.", "Use namespaced tenant cache keys."))
    restored, new_receipt = restore_capsule(root, receipt, session="session-2", turn="turn-2")

    assert "namespaced tenant cache keys" in restored.text
    assert "Use tenant cache keys." not in restored.text
    assert new_receipt["source_hashes"] != receipt["source_hashes"]
    assert new_receipt["restoration_of"] == receipt["receipt_id"]


def test_restore_rejects_missing_node_and_cross_project(tmp_path):
    root = make_root(tmp_path, "one")
    path = write_node(root, "dec-cache", "decision", "accepted", "Use tenant cache keys.")
    capsule = build_capsule(root, "Cache", ["src/cache.py"], "worker")
    receipt = record_receipt(root, capsule)

    other = make_root(tmp_path, "two")
    write_node(other, "dec-cache", "decision", "accepted", "Foreign decision.")
    with pytest.raises(CapsuleError, match="different project"):
        restore_capsule(other, receipt)

    path.unlink()
    with pytest.raises(CapsuleError, match="missing node dec-cache"):
        restore_capsule(root, receipt)


def test_restore_rejects_missing_source_hash(tmp_path):
    root = make_root(tmp_path)
    write_node(root, "dec-cache", "decision", "accepted", "Use tenant cache keys.")
    receipt = record_receipt(root, build_capsule(root, "Cache", ["src/cache.py"], "worker"))
    receipt["source_hashes"] = {}

    with pytest.raises(CapsuleError, match="missing source hash for dec-cache"):
        restore_capsule(root, receipt)


def test_rejects_scope_escape_and_node_symlink_escape(tmp_path):
    root = make_root(tmp_path)
    with pytest.raises(CapsuleError, match="scope path escapes project"):
        build_capsule(root, "Cache", ["../other/secret.py"], "worker")

    outside = tmp_path / "outside.html"
    outside.write_text('''<html><head><meta name="contract-version" content="2"><meta name="node-id" content="wiki-out"><meta name="kind" content="wiki"><meta name="status" content="active"><meta name="affects" content="src/cache.py"></head><body><article data-statement="foreign"></article></body></html>''')
    target = root / "wiki" / "wiki-out.html"
    target.parent.mkdir()
    target.symlink_to(outside)
    with pytest.raises(CapsuleError, match="node path escapes canonical context"):
        build_capsule(root, "Cache", ["src/cache.py"], "worker")


def test_malformed_relevant_node_fails_closed(tmp_path):
    root = make_root(tmp_path)
    write_node(root, "dec-cache", "decision", "accepted", "")
    with pytest.raises(CapsuleError, match="missing statement"):
        build_capsule(root, "Cache", ["src/cache.py"], "worker")


def test_linked_worktree_copy_is_rejected_as_noncanonical(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=main, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=main, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=main, check=True)
    (main / "tracked").write_text("one")
    subprocess.run(["git", "add", "tracked"], cwd=main, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=main, check=True)
    root = make_root(tmp_path, "main")
    write_context_locator(main, root)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "linked", str(linked)], cwd=main, check=True)
    copied = linked / "context"
    copied.mkdir()
    (copied / "index.html").write_text("<html></html>")
    (copied / "config.json").write_text(json.dumps({"repoRoots": [{"path": "."}]}))

    with pytest.raises(CapsuleError, match="not canonical"):
        build_capsule(copied, "Cache", ["src/cache.py"], "worker")


def test_start_task_returns_capsule_and_spills_diagnostics(tmp_path):
    root = make_root(tmp_path)
    page = root / "decisions.html"
    page.write_text('<html><head><meta name="tracks" content="context-only"></head><body></body></html>')
    write_node(root, "dec-cache", "decision", "accepted", "Use tenant cache keys.")
    config = json.loads((root / "config.json").read_text())
    config.update({
        "defaultRole": "worker",
        "agentRoles": {"worker-1": "worker"},
        "permissionProfiles": {"worker": {"acquire_lock": True}},
    })
    (root / "config.json").write_text(json.dumps(config))

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "start-task.py"), "--page", "decisions.html",
         "--intent", "Repair cache", "--result", "Tenant-safe cache", "--path", "src/cache.py",
         "--agent-id", "worker-1"],
        cwd=root.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert "Use tenant cache keys." in payload["capsule"]
    assert all(term not in payload["capsule"] for term in FORBIDDEN_MODEL_TEXT)
    diagnostics = root / payload["diagnostics_file"]
    assert diagnostics.is_file()
    assert "staleness" in json.loads(diagnostics.read_text())
