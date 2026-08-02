import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hook_dispatch import (  # noqa: E402
    block,
    dispatch,
    merge_hook_config,
    normalize_event,
    render_codex_result,
)
from platforms import managed_hook_config  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures" / "hooks"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


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
    assert event.paths == (Path("ok.py"),)
    assert event.unsafe_paths == ("../escape.py", "/tmp/no.py", "NUL payload")


def test_bash_and_collaboration_tools_do_not_invent_paths():
    bash = normalize_event("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
    collaboration = normalize_event("PreToolUse", fixture("codex-collaboration.json"))
    assert bash.paths == ()
    assert collaboration.tool == "collaborationspawn_agent"
    assert collaboration.paths == ()


def test_malformed_or_missing_payload_is_a_safe_empty_event():
    assert normalize_event("PreToolUse", "{").paths == ()
    assert normalize_event("PreToolUse", {}).tool == ""


def test_pretool_block_uses_codex_permission_decision():
    result = render_codex_result(block("read context first"), "PreToolUse")
    assert result == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "read context first",
        }
    }


def test_dispatch_blocks_unsafe_edit_with_one_actionable_reason(tmp_path):
    event = normalize_event("PreToolUse", {"tool_name": "Write", "tool_input": {"file_path": "../escape.py"}})
    result = dispatch(event, tmp_path)
    assert not result.allow
    assert result.reason == "edit paths must stay inside the project"


def test_subagent_start_is_never_blocked_and_output_is_bounded(tmp_path):
    event = normalize_event("SubagentStart", {"tool_name": "collaborationspawn_agent", "agent_id": "child"})
    result = dispatch(event, tmp_path)
    assert result.allow
    assert len(result.context) <= 800


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
