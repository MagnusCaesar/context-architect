import json
import subprocess
import sys
from pathlib import Path

import importlib.util
import pytest


SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "task-lifecycle.py"
SPEC = importlib.util.spec_from_file_location("task_lifecycle", SCRIPT)
LIFECYCLE = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SKILL / "scripts"))
SPEC.loader.exec_module(LIFECYCLE)


def fixture(tmp_path):
    project = tmp_path / "project"
    root = project / "context"
    (root / "active-work").mkdir(parents=True)
    (root / "open-questions").mkdir()
    (root / "index.html").write_text("<html></html>")
    (root / "config.json").write_text(json.dumps({"defaultRole": "readonly", "agentRoles": {"orchestrator": "orchestrator", "readonly": "readonly", "captain": "orchestrator"}, "questionOwners": ["captain", "external"]}))
    (root / "active-work.html").write_text("".join(f'<section><ul data-auto-head="AW-H{i}"><li>empty</li></ul></section>' for i in range(1, 5)))
    (root / "active-work" / "archive.html").write_text("<!-- TASK-ARCHIVE-ROWS -->")
    (root / "open-questions.html").write_text("<!-- CAPTAIN-QUESTION-ROWS -->")
    (root / "open-questions" / "archive.html").write_text("<!-- QUESTION-ARCHIVE-ROWS -->")
    (root / "future-workstreams.html").write_text("<!-- DEFERRED-QUESTION-ROWS -->")
    (root / "ledger.html").write_text('<html><body><section id="events"><table><tbody></tbody></table></section></body></html>')
    return project, root


def run(project, *args, ok=True):
    result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=project, capture_output=True, text=True, timeout=10)
    assert (result.returncode == 0) is ok, result.stderr
    return result


def make_task(project, task_id="AW-001", slug="task", status="ready"):
    return run(project, "new-task", "--task-id", task_id, "--slug", slug, "--title", "Task", "--summary", "A durable task statement", "--parent", "AW-H1", "--status", status, "--source-ids", "fixture", "--source", "evidence|../index.html", "--verify", "check", "--contingency", "wait")


def test_task_question_answer_and_router_lifecycle(tmp_path):
    project, root = fixture(tmp_path)
    make_task(project)
    task = root / "active-work" / "aw-001-task.html"
    assert 'id="AW-001"' in task.read_text()
    assert "AW-001" in (root / "active-work.html").read_text()
    run(project, "new-question", "--question-id", "OQ-001", "--slug", "choice", "--title", "Choice", "--task", "AW-001", "--ask", "Choose?", "--owner", "captain", "--contingency", "wait", "--source", "context|../index.html")
    qpath = root / "open-questions" / "oq-001-choice.html"
    assert 'content="blocked"' in task.read_text()
    assert 'data-lifecycle="question-OQ-001"' in (root / "open-questions.html").read_text()
    run(project, "new-question", "--question-id", "OQ-003", "--slug", "second", "--title", "Second", "--task", "AW-001", "--ask", "Second?", "--owner", "captain", "--contingency", "wait")
    run(project, "answer-question", "--question-id", "OQ-001", "--answer", "First answer")
    run(project, "answer-question", "--question-id", "OQ-001", "--answer", r"Updated answer \d+ literal")
    assert 'content="blocked"' in task.read_text()
    run(project, "answer-question", "--question-id", "OQ-003", "--answer", "Resolved")
    assert 'content="ready"' in task.read_text()
    assert r"Updated answer \d+ literal" in qpath.read_text() and "First answer" not in qpath.read_text()
    archive = (root / "open-questions" / "archive.html").read_text()
    assert archive.count('data-lifecycle="answered-OQ-001"') == 1
    assert "data-lifecycle=\"question-OQ-001\"" not in (root / "open-questions.html").read_text()


def test_preserves_preexisting_blocked_task_state(tmp_path):
    project, root = fixture(tmp_path)
    make_task(project)
    task = root / "active-work" / "aw-001-task.html"
    task.write_text(task.read_text().replace('name="status" content="ready"', 'name="status" content="blocked"', 1).replace("<dt>State</dt><dd>ready</dd>", "<dt>State</dt><dd>blocked</dd>", 1))
    run(project, "new-question", "--question-id", "OQ-001", "--slug", "choice", "--title", "Choice", "--task", "AW-001", "--ask", "Choose?", "--owner", "captain", "--contingency", "wait")
    run(project, "answer-question", "--question-id", "OQ-001", "--answer", "Resolved")
    assert 'content="blocked"' in task.read_text()


def test_parked_preserves_state_defer_and_captain_disposition(tmp_path):
    project, root = fixture(tmp_path)
    make_task(project, status="in-progress")
    task = root / "active-work" / "aw-001-task.html"
    run(project, "new-question", "--question-id", "OQ-002", "--slug", "later", "--title", "Later", "--task", "AW-001", "--ask", "Later?", "--owner", "captain", "--contingency", "wait", "--status", "parked")
    assert 'content="in-progress"' in task.read_text()
    run(project, "defer-question", "--question-id", "OQ-002", "--trigger", "external reply")
    assert 'content="deferred"' in task.read_text()
    assert "external reply" in (root / "future-workstreams.html").read_text()
    run(project, "answer-question", "--question-id", "OQ-002", "--answer", "Reply arrived")
    assert 'content="in-progress"' in task.read_text()
    assert "data-lifecycle=\"deferred-OQ-002\"" not in (root / "future-workstreams.html").read_text()
    make_task(project, "AW-003", "awaiting", "awaiting-captain")
    run(project, "archive-task", "--task-id", "AW-003", "--final", "accepted", "--note", "approved", ok=False)
    run(project, "archive-task", "--task-id", "AW-003", "--final", "accepted", "--note", "approved", "--actor-id", "captain", "--confirm-captain")
    assert 'content="accepted"' in (root / "active-work" / "aw-003-awaiting.html").read_text()


def test_terminal_disposition_cannot_be_undone_by_question_updates(tmp_path):
    project, root = fixture(tmp_path)
    make_task(project, "AW-001", "awaiting", "awaiting-captain")
    run(project, "new-question", "--question-id", "OQ-001", "--slug", "choice", "--title", "Choice", "--task", "AW-001", "--ask", "Choose?", "--owner", "captain", "--contingency", "wait")
    task = root / "active-work" / "aw-001-awaiting.html"
    task.write_text(task.read_text().replace('name="status" content="blocked"', 'name="status" content="awaiting-captain"', 1))
    run(project, "archive-task", "--task-id", "AW-001", "--final", "accepted", "--note", r"approved \d+", "--actor-id", "captain", "--confirm-captain")
    assert r"approved \d+" in task.read_text()
    run(project, "defer-question", "--question-id", "OQ-001", "--trigger", "later", ok=False)
    run(project, "answer-question", "--question-id", "OQ-001", "--answer", "Resolved after disposition")
    assert 'content="accepted"' in task.read_text()
    run(project, "new-question", "--question-id", "OQ-002", "--slug", "blocked", "--title", "Blocked", "--task", "AW-001", "--ask", "Block?", "--owner", "captain", "--contingency", "wait", ok=False)


def test_rejects_unknown_actor_and_unsafe_paths_before_writing(tmp_path):
    project, root = fixture(tmp_path)
    before = (root / "active-work.html").read_text()
    run(project, "new-task", "--task-id", "AW-001", "--slug", "task", "--title", "Task", "--summary", "statement", "--parent", "AW-H1", "--status", "ready", "--source-ids", "fixture", "--source", "bad|../../outside", "--verify", "check", "--contingency", "wait", ok=False)
    run(project, "new-task", "--task-id", "AW-001", "--slug", "task", "--title", "Task", "--summary", "statement", "--parent", "AW-H1", "--status", "ready", "--source-ids", "fixture", "--verify", "check", "--contingency", "wait", "--actor-id", "readonly", ok=False)
    assert (root / "active-work.html").read_text() == before
    assert not list((root / "active-work").glob("aw-*.html"))
    assert LIFECYCLE.validate_lifecycle(root) == []


def test_rolls_back_previously_written_pages_on_batch_failure(tmp_path, monkeypatch):
    _project, root = fixture(tmp_path)
    first, second = root / "active-work.html", root / "open-questions.html"
    before = {first: first.read_text(), second: second.read_text()}
    original = LIFECYCLE.write_atomic
    calls = 0

    def fail_second(path, content, context_root=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture write failure")
        original(path, content, context_root=context_root)

    monkeypatch.setattr(LIFECYCLE, "write_atomic", fail_second)
    with pytest.raises(OSError, match="fixture write failure"):
        LIFECYCLE.commit(root, "orchestrator", "test", "active-work.html", {first: "changed", second: "changed"}, "test")
    assert {first: first.read_text(), second: second.read_text()} == before


def test_answer_respects_deferred_router_lock(tmp_path):
    project, root = fixture(tmp_path)
    make_task(project)
    run(project, "new-question", "--question-id", "OQ-001", "--slug", "choice", "--title", "Choice", "--task", "AW-001", "--ask", "Choose?", "--owner", "captain", "--contingency", "wait")
    future = root / "future-workstreams.html"
    future.write_text('<meta name="locked" content="true"><meta name="locked-by" content="worker">' + future.read_text())
    question = root / "open-questions" / "oq-001-choice.html"
    before = question.read_text()
    run(project, "answer-question", "--question-id", "OQ-001", "--answer", "Resolved", ok=False)
    assert question.read_text() == before


def test_rolls_back_pages_when_audit_append_fails(tmp_path, monkeypatch):
    _project, root = fixture(tmp_path)
    page = root / "active-work.html"
    before = page.read_text()
    monkeypatch.setattr(LIFECYCLE, "append_ledger_event", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("audit failure")))
    with pytest.raises(OSError, match="audit failure"):
        LIFECYCLE.commit(root, "orchestrator", "test", "active-work.html", {page: "changed"}, "test")
    assert page.read_text() == before


def test_refuses_other_owners_lock_and_symlink_output_directory(tmp_path):
    project, root = fixture(tmp_path)
    make_task(project)
    task = root / "active-work" / "aw-001-task.html"
    task.write_text(task.read_text().replace('<meta name="locked" content="false">', '<meta name="locked" content="true">').replace('<meta name="locked-by" content="">', '<meta name="locked-by" content="worker">'))
    before = (root / "open-questions.html").read_text()
    run(project, "new-question", "--question-id", "OQ-001", "--slug", "choice", "--title", "Choice", "--task", "AW-001", "--ask", "Choose?", "--owner", "captain", "--contingency", "wait", ok=False)
    assert (root / "open-questions.html").read_text() == before
    assert not list((root / "open-questions").glob("oq-*.html"))

    link_project, link_root = fixture(tmp_path / "symlink")
    (link_root / "active-work" / "archive.html").unlink()
    (link_root / "active-work").rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (link_root / "active-work").symlink_to(outside, target_is_directory=True)
    run(link_project, "new-task", "--task-id", "AW-002", "--slug", "escape", "--title", "Escape", "--summary", "No write", "--parent", "AW-H1", "--status", "ready", "--source-ids", "fixture", "--verify", "check", "--contingency", "wait", ok=False)
    assert list(outside.iterdir()) == []
