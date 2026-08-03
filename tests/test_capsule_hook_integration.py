import html
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bootstrap  # noqa: E402
from context_utils import read_ledger_events  # noqa: E402
from hook_dispatch import dispatch, normalize_event, render_claude_result, render_codex_result  # noqa: E402
from task_capsule import build_capsule  # noqa: E402


FORBIDDEN = (
    "ledger-events.ndjson",
    "mutex",
    "receipt_id",
    "hygiene",
    "project-registry",
    "archive",
    "Diagnostic written",
    "status=",
)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write_node(root: Path, statement: str, *, node_id: str = "dec-cache", affects: str = "src/cache.py") -> Path:
    path = root / "decisions" / f"{node_id}.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(f'''<html><head>
<meta name="contract-version" content="2">
<meta name="node-id" content="{node_id}">
<meta name="kind" content="decision">
<meta name="status" content="accepted">
<meta name="affects" content="{affects}">
<meta name="visibility" content="agent">
</head><body><article id="{node_id}" data-statement="{statement}"></article></body></html>''')
    return path


def linked_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    main = tmp_path / "main"
    linked = tmp_path / "linked"
    main.mkdir()
    git(main, "init", "-b", "main")
    git(main, "config", "user.email", "test@example.com")
    git(main, "config", "user.name", "Test")
    git(main, "commit", "--allow-empty", "-m", "initial")
    git(main, "worktree", "add", "-b", "linked", str(linked))
    root = bootstrap.generate_skeleton(
        linked,
        [],
        config={"projectName": "demo", "repoRoots": [{"path": ".", "label": "main"}]},
        platforms=("claude", "codex"),
    )
    return main, linked, root


def subagent_event(linked: Path, *, session: str = "s1", turn: str = "t1"):
    return normalize_event("SubagentStart", {
        "cwd": str(linked),
        "session_id": session,
        "turn_id": turn,
        "agent_type": "worker",
        "task": "Repair cache isolation",
        "result": "Tenant-safe cache reads",
        "scope": ["src/cache.py"],
        "links": ["decisions/dec-cache.html#dec-cache"],
    })


def test_linked_worktree_installs_both_harnesses_against_canonical_context(tmp_path):
    main, linked, root = linked_project(tmp_path)

    assert root == main / "context"
    for path in (linked / ".claude" / "settings.json", linked / ".codex" / "hooks.json"):
        text = path.read_text()
        assert str(root / "scripts" / "hook_dispatch.py") in text
        assert f"--context-root {root}" in text
        assert str(linked / "context") not in text


def test_linked_worktree_accepts_absolute_project_and_canonical_context_edits(tmp_path):
    _, linked, root = linked_project(tmp_path)
    page = root / "decisions.html"
    page.write_text(
        page.read_text()
        .replace('content="false"', 'content="true"', 1)
        .replace('name="locked-by" content=""', 'name="locked-by" content="agent-linked"', 1)
    )
    source = linked / "src" / "cache.py"
    source.parent.mkdir()
    source.write_text("cache")

    for path in (source, page):
        event = normalize_event("PreToolUse", {
            "cwd": str(linked),
            "agent_id": "agent-linked",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path)},
        })
        assert dispatch(event, root).allow


def test_linked_worktree_rejects_absolute_outside_and_symlink_escape_edits(tmp_path):
    _, linked, root = linked_project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("private")
    source_link = linked / "escape.py"
    source_link.symlink_to(outside)
    context_link = root / "decisions" / "escape.html"
    context_link.symlink_to(outside)

    for path in (outside, source_link, context_link):
        event = normalize_event("PreToolUse", {
            "cwd": str(linked),
            "agent_id": "agent-linked",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(path)},
        })
        result = dispatch(event, root)
        assert not result.allow
        assert result.reason == "edit paths must stay inside the project or canonical context"


def test_linked_absolute_canonical_edit_still_enforces_shared_lock_owner(tmp_path):
    _, linked, root = linked_project(tmp_path)
    config = json.loads((root / "config.json").read_text())
    config["autoAcquireOnEdit"] = False
    (root / "config.json").write_text(json.dumps(config))
    page = root / "decisions.html"
    page.write_text(
        page.read_text()
        .replace('content="false"', 'content="true"', 1)
        .replace('name="locked-by" content=""', 'name="locked-by" content="other-agent"', 1)
    )
    event = normalize_event("PreToolUse", {
        "cwd": str(linked),
        "agent_id": "agent-linked",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(page)},
    })

    result = dispatch(event, root)

    assert not result.allow
    assert "locked by other-agent" in result.reason


def test_subagent_protocol_additional_context_is_exact_canonical_capsule(tmp_path):
    _, linked, root = linked_project(tmp_path)
    write_node(root, "Cache keys include tenant ID.")
    event = subagent_event(linked)
    expected = build_capsule(
        root,
        {
            "task": event.task,
            "result": event.result,
            "links": event.links,
        },
        event.scope,
        event.role,
    )

    result = dispatch(event, linked / "context")

    assert result.context == expected.text
    assert all(term not in result.context for term in FORBIDDEN)
    for render in (render_codex_result, render_claude_result):
        assert render(result, "SubagentStart")["hookSpecificOutput"]["additionalContext"] == expected.text
    receipts = [event for event in read_ledger_events(root) if event.get("event") == "task_capsule"]
    assert len(receipts) == 1
    assert receipts[0]["session"] == "s1"
    assert not (root / ".hook-receipts").exists()
    dispatcher = (SCRIPTS / "hook_dispatch.py").read_text()
    assert 'context_root / "scripts" / "start-task.py"' not in dispatcher


def test_both_harness_clis_emit_only_canonical_capsule_text(tmp_path):
    _, linked, root = linked_project(tmp_path)
    write_node(root, "Cache keys include tenant ID.")
    payload = {
        "cwd": str(linked),
        "session_id": "cli-session",
        "turn_id": "cli-turn",
        "agent_type": "worker",
        "task": "Repair cache isolation",
        "result": "Tenant-safe cache reads",
        "scope": ["src/cache.py"],
        "links": ["decisions/dec-cache.html#dec-cache"],
    }
    event = normalize_event("SubagentStart", payload)
    expected = build_capsule(
        root,
        {"task": event.task, "result": event.result, "links": event.links},
        event.scope,
        event.role,
    ).text

    for platform in ("claude", "codex"):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "hook_dispatch.py"),
                "--platform",
                platform,
                "--event",
                "SubagentStart",
                "--context-root",
                str(linked / "context"),
            ],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(completed.stdout) == {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": expected,
            }
        }


def test_postcompact_rebuilds_changed_node_through_canonical_receipt(tmp_path):
    _, linked, root = linked_project(tmp_path)
    node = write_node(root, "Old cache rule.")
    dispatch(subagent_event(linked), linked / "context")
    first = [event for event in read_ledger_events(root) if event.get("event") == "task_capsule"][-1]
    node.write_text(node.read_text().replace("Old cache rule.", "Current tenant cache rule."))

    restored = dispatch(normalize_event("PostCompact", {
        "cwd": str(linked), "session_id": "s1", "turn_id": "t2",
    }), linked / "context").context

    assert "Current tenant cache rule." in restored
    assert "Old cache rule." not in restored
    receipts = [event for event in read_ledger_events(root) if event.get("event") == "task_capsule"]
    assert len(receipts) == 2
    assert receipts[-1]["restoration_of"] == first["receipt_id"]
    assert receipts[-1]["source_hashes"] != first["source_hashes"]


def test_firstmate_route_is_expressed_inside_capsule_only(tmp_path):
    firstmate = tmp_path / "firstmate" / "context"
    firstmate.mkdir(parents=True)
    (firstmate / "index.html").write_text("<html></html>")
    (firstmate / "config.json").write_text(json.dumps({"scope": "global", "repoRoots": [{"path": "."}]}))
    project = tmp_path / "beta"
    project.mkdir()
    root = bootstrap.generate_skeleton(
        project,
        [],
        config={"projectName": "beta", "repoRoots": [{"path": "."}]},
        platforms=("codex",),
    )
    write_node(root, "Beta failures use the scoped recovery.", node_id="dec-beta", affects="src/beta.py")
    (firstmate / "project-registry.html").write_text(
        f'<article class="project">beta | {root} | Beta project | blocked</article>'
    )
    event = normalize_event("SubagentStart", {
        "session_id": "fm-s1",
        "agent_type": "worker",
        "task": "Audit beta failures",
        "result": "Explain the scoped recovery",
        "scope": ["src/beta.py"],
    })

    text = dispatch(event, firstmate).context

    assert text.startswith("Task: Audit beta failures")
    assert f"registered project beta at {root}" in text
    assert "Beta failures use the scoped recovery." in text
    assert all(term not in text for term in FORBIDDEN)
    assert "Firstmate route:" not in text
    assert any(event.get("session") == "fm-s1" for event in read_ledger_events(root))


@pytest.mark.parametrize(("platform", "event_name"), (("claude", "Stop"), ("codex", "SessionEnd")))
def test_stop_protocol_privately_captures_one_bounded_candidate(tmp_path, platform, event_name):
    root = tmp_path / "firstmate" / "context"
    root.mkdir(parents=True)
    (root / "index.html").write_text("<html></html>")
    (root / "config.json").write_text(json.dumps({"scope": "global", "repoRoots": [{"path": "."}]}))
    (root / "capture-inbox.html").write_text('<html><body><section id="candidates"></section></body></html>')
    private = "TOKEN=supersecret " + "x" * 1000
    payload = {"session_id": "session-private", "final_message": f"Failure found: {private}"}

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hook_dispatch.py"),
            "--platform",
            platform,
            "--event",
            event_name,
            "--context-root",
            str(root),
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(completed.stdout) == {"hookSpecificOutput": {"hookEventName": event_name}}
    assert "supersecret" not in completed.stdout
    article = re.search(r'<article class="candidate"[^>]*>', (root / "capture-inbox.html").read_text())
    assert article
    summary = html.unescape(re.search(r'data-summary="([^"]*)"', article.group()).group(1))
    assert len(summary) <= 500
    assert "supersecret" not in summary
    assert "[redacted]" in summary
    assert 'data-kind="failure"' in article.group()
    assert 'data-source="session-private"' in article.group()
    assert (root / "capture-inbox.html").stat().st_mode & 0o777 == 0o600
