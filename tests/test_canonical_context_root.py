import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bootstrap  # noqa: E402
from context_utils import (  # noqa: E402
    ContextRootError,
    append_ledger_event,
    canonical_context_root,
    find_context_root,
    read_ledger_events,
    read_meta,
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def git_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    main = tmp_path / "main"
    linked = tmp_path / "linked"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.email", "test@example.com")
    git(main, "config", "user.name", "Test")
    git(main, "commit", "--allow-empty", "-m", "initial")
    bootstrap.generate_skeleton(main, [], config={})
    git(main, "worktree", "add", "-b", "linked", str(linked))
    return main, linked, main / ".git" / "context-architecture.json"


def load_start_task():
    spec = importlib.util.spec_from_file_location("start_task_for_root_test", SCRIPTS / "start-task.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_linked_worktree_shares_context_locks_and_ledger(tmp_path):
    main, linked, locator = git_project(tmp_path)

    assert locator.exists()
    assert canonical_context_root(main) == main / "context"
    assert canonical_context_root(linked) == main / "context"

    start_task = load_start_task()
    main_context = canonical_context_root(main)
    linked_context = canonical_context_root(linked)
    assert start_task.acquire_lock(main_context, "wiki.html", "agent-main")["acquired"]
    assert read_meta(linked_context / "wiki.html", "locked-by") == "agent-main"

    append_ledger_event(
        linked_context,
        "shared-root-test",
        "wiki.html",
        "agent-linked",
        "seen",
        trigger_hygiene=False,
    )
    assert any(
        event.get("event") == "shared-root-test"
        for event in read_ledger_events(main_context)
    )


def test_bootstrap_from_linked_worktree_initializes_primary_context_only(tmp_path):
    main = tmp_path / "main"
    linked = tmp_path / "linked"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.email", "test@example.com")
    git(main, "config", "user.name", "Test")
    git(main, "commit", "--allow-empty", "-m", "initial")
    git(main, "worktree", "add", "-b", "linked", str(linked))

    context = bootstrap.generate_skeleton(linked, [], config={})

    assert context == main / "context"
    assert canonical_context_root(linked) == context
    assert not (linked / "context").exists()


def test_non_git_project_keeps_local_fallback(tmp_path, monkeypatch):
    context = tmp_path / "project" / "context"
    context.mkdir(parents=True)
    (context / "index.html").write_text("<html></html>")

    assert canonical_context_root(context.parent) == context
    monkeypatch.chdir(context.parent)
    assert find_context_root() == context


def test_linked_worktree_copy_is_never_selected(tmp_path, monkeypatch):
    main, linked, _ = git_project(tmp_path)
    copied = linked / "context"
    copied.mkdir()
    (copied / "index.html").write_text("COPIED")

    monkeypatch.chdir(linked)
    assert canonical_context_root(linked) == main / "context"
    assert find_context_root() == main / "context"


def test_generate_docs_ignores_linked_worktree_context_copy(tmp_path):
    main, linked, _ = git_project(tmp_path)
    canonical_page = main / "context" / "canonical-only.html"
    canonical_page.write_text("<html><body><h1>Canonical only</h1></body></html>")
    copied = linked / "context"
    copied.mkdir()
    (copied / "index.html").write_text("<html><body><h1>Copied</h1></body></html>")

    subprocess.run(
        [sys.executable, str(main / "context" / "scripts" / "generate-docs.py")],
        cwd=linked,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (main / "docs" / "context" / "canonical-only.md").exists()
    assert not (linked / "docs" / "context").exists()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{bad", "malformed"),
        ({"version": 1, "path": "../../other/context", "anchor": "unused", "identity": "unused"}, "absolute"),
    ],
)
def test_malformed_or_relative_locator_fails_closed(tmp_path, payload, message):
    main, _, locator = git_project(tmp_path)
    locator.write_text(payload if isinstance(payload, str) else json.dumps(payload))

    with pytest.raises(ContextRootError, match=message):
        canonical_context_root(main)


def test_missing_locator_target_fails_closed(tmp_path):
    main, _, locator = git_project(tmp_path)
    data = json.loads(locator.read_text())
    data["path"] = str(main / "missing-context")
    locator.write_text(json.dumps(data))

    with pytest.raises(ContextRootError, match="does not exist"):
        canonical_context_root(main)


def test_locator_target_outside_registered_root_fails_closed(tmp_path):
    main, _, locator = git_project(tmp_path)
    outside = tmp_path / "outside" / "context"
    outside.mkdir(parents=True)
    (outside / "index.html").write_text("<html></html>")
    data = json.loads(locator.read_text())
    data["path"] = str(outside)
    locator.write_text(json.dumps(data))

    with pytest.raises(ContextRootError, match="outside registered root"):
        canonical_context_root(main)


def test_symlink_escape_fails_closed(tmp_path):
    main, _, locator = git_project(tmp_path)
    outside = tmp_path / "outside" / "context"
    outside.mkdir(parents=True)
    (outside / "index.html").write_text("<html></html>")
    escape = main / "context-link"
    escape.symlink_to(outside, target_is_directory=True)
    data = json.loads(locator.read_text())
    data["path"] = str(escape)
    locator.write_text(json.dumps(data))

    with pytest.raises(ContextRootError, match="outside registered root"):
        canonical_context_root(main)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", 2, "unsupported version"),
        ("anchor", "/tmp/not-this-repository", "anchor"),
        ("identity", "copied", "identity"),
    ],
)
def test_locator_version_anchor_and_identity_are_verified(tmp_path, field, value, message):
    main, _, locator = git_project(tmp_path)
    data = json.loads(locator.read_text())
    data[field] = value
    locator.write_text(json.dumps(data))

    with pytest.raises(ContextRootError, match=message):
        canonical_context_root(main)


def test_linked_checkout_without_locator_rejects_local_copy(tmp_path):
    main = tmp_path / "main"
    linked = tmp_path / "linked"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.email", "test@example.com")
    git(main, "config", "user.name", "Test")
    git(main, "commit", "--allow-empty", "-m", "initial")
    git(main, "worktree", "add", "-b", "linked", str(linked))
    copied = linked / "context"
    copied.mkdir()
    (copied / "index.html").write_text("COPIED")

    with pytest.raises(ContextRootError, match="locator missing"):
        canonical_context_root(linked)
