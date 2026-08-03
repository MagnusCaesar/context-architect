import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hook_dispatch import (  # noqa: E402
    Result,
    block,
    dispatch,
    merge_hook_config,
    normalize_event,
    render_claude_result,
    render_codex_result,
)
from platforms import managed_hook_config  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures" / "hooks"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def firstmate_context(tmp_path):
    context = tmp_path / "firstmate" / "context"; context.mkdir(parents=True)
    (context / "config.json").write_text(json.dumps({"scope": "global"}))
    alpha = tmp_path / "alpha" / "context"; beta = tmp_path / "beta" / "context"
    alpha.mkdir(parents=True); beta.mkdir(parents=True)
    (alpha / "index.html").write_text("ALPHA_NODE_SECRET")
    (beta / "index.html").write_text("BETA_CAPTURE_SECRET")
    (context / "project-registry.html").write_text(
        '<section id="projects">'
        f'<article class="project">alpha | {alpha} | Alpha | active</article>'
        f'<article class="project">beta | {beta} | Beta | blocked</article>'
        '</section>'
    )
    (context / ".validation-state.json").write_text(json.dumps({"status": "warning"}))
    return context, alpha, beta


def test_claude_edit_normalizes_ids_metadata_and_space_path():
    event = normalize_event("PreToolUse", fixture("claude-edit.json"))
    assert event.platform == "claude"
    assert event.tool == "Edit"
    assert event.paths == (Path("dir with space/file.py"),)
    assert (event.session_id, event.turn_id, event.agent_id) == ("claude-session", "turn-1", "agent-7")
    assert (event.permission_mode, event.model) == ("default", "claude-test")


def test_codex_apply_patch_extracts_every_affected_path():
    event = normalize_event("PreToolUse", fixture("codex-multi-file-patch.json"))
    assert event.platform == "codex"
    assert event.tool == "apply_patch"
    assert event.paths == (Path("a.py"), Path("dir with space/b.py"), Path("old.py"), Path("source.py"), Path("moved.py"))


def test_patch_rejects_unsafe_and_fake_markers():
    event = normalize_event("PreToolUse", {
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n*** Add File: ../escape.py\n*** Add File: /tmp/no.py\n*** Add File: ok.py\n+*** Add File: fake.py\n*** End Patch\x00"},
    })
    assert event.paths == (Path("/tmp/no.py"), Path("ok.py"))
    assert event.unsafe_paths == ("../escape.py", "NUL payload")


def test_bash_and_collaboration_tools_do_not_invent_paths():
    bash = normalize_event("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    collaboration = normalize_event("PreToolUse", fixture("codex-collaboration.json"))
    assert bash.paths == ()
    assert collaboration.tool == "collaborationspawn_agent"
    assert collaboration.paths == ()


def test_malformed_or_missing_payload_is_a_safe_empty_event():
    assert normalize_event("PreToolUse", "{").paths == ()
    assert normalize_event("PreToolUse", {}).tool == ""


@pytest.mark.parametrize("tool_input", [None, {}, "not-an-object"])
def test_malformed_edit_payload_fails_closed(tmp_path, tool_input):
    event = normalize_event("PreToolUse", {"tool_name": "Write", "tool_input": tool_input})
    result = dispatch(event, tmp_path)

    assert not result.allow
    assert "valid path" in result.reason


def test_pretool_block_uses_codex_permission_decision():
    result = render_codex_result(block("read context first"), "PreToolUse")
    assert result == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "read context first",
        }
    }


def test_claude_subagent_stop_continues_after_validation_failure():
    result = render_claude_result(Result(context="context validation failed", continue_=True), "SubagentStop")
    assert result == {"decision": "block", "reason": "context validation failed"}


def test_dispatch_blocks_unsafe_edit_with_one_actionable_reason(tmp_path):
    event = normalize_event("PreToolUse", {"tool_name": "Write", "tool_input": {"file_path": "../escape.py"}})
    result = dispatch(event, tmp_path)
    assert not result.allow
    assert result.reason == "edit paths must stay inside the project or canonical context"


def test_subagent_start_without_role_task_or_scope_injects_nothing(tmp_path):
    event = normalize_event("SubagentStart", {"agent_id": ""})
    assert dispatch(event, tmp_path).context == ""


def test_session_start_injects_no_control_plane_status(tmp_path):
    context, _, _ = firstmate_context(tmp_path)
    assert dispatch(normalize_event("SessionStart", {}), context).context == ""


def test_subagent_payload_does_not_stringify_sensitive_nested_containers(tmp_path):
    event = normalize_event("SubagentStart", {
        "agent_type": {"password": "role-secret"},
        "task": {"token": "task-secret"},
        "scope": [{"api_key": "scope-secret"}, "scripts/hook_dispatch.py"],
    })
    context = dispatch(event, tmp_path).context
    assert event.role == ""
    assert event.task == ""
    assert event.scope == ("scripts/hook_dispatch.py",)
    assert all(secret not in context for secret in ("role-secret", "task-secret", "scope-secret"))


def test_subagent_stop_continues_only_when_validation_concretely_fails(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    validator = scripts / "validate.py"
    validator.write_text("import argparse\nargparse.ArgumentParser().parse_args()\n")
    event = normalize_event("SubagentStop", {})
    assert not dispatch(event, tmp_path).continue_
    validator.write_text("raise SystemExit(1)\n")
    assert dispatch(event, tmp_path).continue_


def test_post_edit_runs_shared_freshness_check_for_source_paths(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check-freshness.py").write_text(
        "from pathlib import Path\nPath('freshness-ran').write_text('yes')\n"
    )
    event = normalize_event("PostToolUse", {"tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}})
    assert dispatch(event, tmp_path).allow
    assert (tmp_path / "freshness-ran").read_text() == "yes"


def test_pretool_source_edit_requires_its_tracking_page_read(tmp_path):
    project = tmp_path / "project"
    context = project / "context"
    context.mkdir(parents=True)
    (context / "module.html").write_text('<meta name="tracks" content="src/a.py">')
    edit = normalize_event("PreToolUse", {
        "session_id": "session-1", "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"},
    })
    denied = dispatch(edit, context)
    assert not denied.allow
    assert denied.reason == "read context/module.html before editing src/a.py"

    read = normalize_event("PostToolUse", {
        "session_id": "session-1", "tool_name": "Read", "tool_input": {"file_path": "context/module.html"},
    })
    assert dispatch(read, context).allow
    assert dispatch(edit, context).allow


def test_tracking_page_under_repo_with_docs_ancestor_is_not_skipped(tmp_path):
    project = tmp_path / "docs" / "project"
    context = project / "context"
    context.mkdir(parents=True)
    (context / "module.html").write_text('<meta name="tracks" content="src/a.py">')
    event = normalize_event("PreToolUse", {
        "session_id": "session-1", "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"},
    })
    result = dispatch(event, context)
    assert not result.allow
    assert result.reason == "read context/module.html before editing src/a.py"


def test_pretool_context_edit_enforces_existing_lock_owner(tmp_path):
    project = tmp_path / "project"
    context = project / "context"
    context.mkdir(parents=True)
    (context / "config.json").write_text(json.dumps({"autoAcquireOnEdit": False}))
    (context / "decisions.html").write_text(
        '<meta name="locked" content="true"><meta name="locked-by" content="other-agent">'
    )
    event = normalize_event("PreToolUse", {
        "agent_id": "this-agent", "tool_name": "Edit", "tool_input": {"file_path": "context/decisions.html"},
    })
    result = dispatch(event, context)
    assert not result.allow
    assert result.reason == "context/decisions.html is locked by other-agent; run start-task.py first"


def test_pretool_blocks_owned_read_only_source_directories(tmp_path):
    event = normalize_event("PreToolUse", {
        "tool_name": "Write", "tool_input": {"file_path": "logs/result.txt"},
    })
    result = dispatch(event, tmp_path / "context")
    assert not result.allow
    assert result.reason == "logs/result.txt is in a read-only source directory"


def test_postcompact_missing_receipt_injects_nothing(tmp_path):
    event = normalize_event("PostCompact", {"session_id": "session-1"})
    assert dispatch(event, tmp_path).context == ""


def test_merge_replaces_only_managed_entries_without_hook_order_assumption():
    existing = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Edit", "hooks": [{"command": "user-check"}]},
                {"matcher": "Write", "hooks": [{"command": "python old/hook_dispatch.py --managed-group context-architecture"}]},
            ],
            "Stop": [{"hooks": [{"command": "plugin-stop"}]}],
        },
        "plugin": {"enabled": True},
    }
    managed = {"hooks": {"PreToolUse": [{"matcher": "Edit|Write", "hooks": [{"command": "python hook_dispatch.py --managed-group context-architecture"}]}]}}
    merged = merge_hook_config(existing, managed)
    assert merged["plugin"] == {"enabled": True}
    assert merged["hooks"]["Stop"] == existing["hooks"]["Stop"]
    assert any("user-check" in json.dumps(group) for group in merged["hooks"]["PreToolUse"])
    assert sum("--managed-group context-architecture" in json.dumps(group) for group in merged["hooks"]["PreToolUse"]) == 1
    assert merge_hook_config(merged, managed) == merged


def test_merge_preserves_unrelated_command_containing_marker_text():
    unrelated = {"matcher": "Edit", "hooks": [{"command": "echo context-architecture"}]}
    existing = {"hooks": {"PreToolUse": [unrelated]}}
    managed = {"hooks": {"PreToolUse": [{"hooks": [{"command": "python hook_dispatch.py --managed-group context-architecture"}]}]}}
    merged = merge_hook_config(existing, managed)
    assert unrelated in merged["hooks"]["PreToolUse"]


def test_merge_removes_exact_legacy_wrapper_but_preserves_plugin_group():
    legacy = {"hooks": [{"type": "command", "command": "bash /project/context/hooks/pre-edit-context-gate.sh"}]}
    plugin = {"hooks": [{"type": "command", "command": "/plugin/pre-edit-context-gate.sh"}]}
    existing = {"hooks": {"PreToolUse": [legacy, plugin]}}
    merged = merge_hook_config(existing, {"hooks": {}})
    assert merged["hooks"]["PreToolUse"] == [plugin]


def test_merge_returns_invalid_json_bytes_unchanged():
    raw = b'{ bad json\n'
    assert merge_hook_config(raw, {"hooks": {}}) is raw


def test_bootstrap_merges_dispatcher_hooks_for_both_platforms(tmp_path):
    (tmp_path / ".claude").mkdir()
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "plugin-stop"}]}]}}))
    bootstrap = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.py"
    result = subprocess.run(
        [sys.executable, str(bootstrap), "--target", str(tmp_path), "--platform", "both"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    claude = json.loads(settings.read_text())
    codex = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    assert "plugin-stop" in json.dumps(claude)
    assert "hook_dispatch.py" in json.dumps(claude)
    assert "hook_dispatch.py" in json.dumps(codex)


def test_generated_dispatcher_command_quotes_a_space_in_the_project_path(tmp_path):
    command = managed_hook_config("codex", tmp_path / "dir with space")["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    words = shlex.split(command)
    assert words[1].endswith("dir with space/context/scripts/hook_dispatch.py")


def test_refresh_removes_only_superseded_target_hook_files(tmp_path):
    bootstrap = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.py"
    subprocess.run([sys.executable, str(bootstrap), "--target", str(tmp_path), "--platform", "claude"], check=True, capture_output=True)
    hooks = tmp_path / "context" / "hooks"
    legacy = hooks / "pre-edit-context-gate.sh"
    custom = hooks / "custom-project-hook.sh"
    legacy.write_text("legacy")
    custom.write_text("custom")
    subprocess.run([sys.executable, str(bootstrap), "--target", str(tmp_path), "--refresh"], check=True, capture_output=True)
    assert not legacy.exists()
    assert custom.read_text() == "custom"
