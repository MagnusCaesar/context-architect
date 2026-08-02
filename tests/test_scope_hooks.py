import json, subprocess, sys, tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"

def _boot(target, *extra):
    subprocess.run([sys.executable, str(BOOTSTRAP), "--target", str(target), *extra],
                   capture_output=True, text=True)
    return json.loads((Path(target) / ".claude" / "settings.json").read_text())["hooks"]

def test_global_registers_sessionstart_and_stop():
    with tempfile.TemporaryDirectory() as d:
        hooks = _boot(d, "--scope", "global")
        assert "SessionStart" in hooks
        assert "Stop" in hooks
        ss = json.dumps(hooks["SessionStart"])
        assert "session-start-inject.sh" in ss
        assert "capture-on-stop.sh" in json.dumps(hooks["Stop"])

def test_project_registers_stop_not_sessionstart():
    with tempfile.TemporaryDirectory() as d:
        hooks = _boot(d)  # default project
        assert "SessionStart" not in hooks
        assert "Stop" in hooks
        assert "UserPromptSubmit" in hooks and "PreToolUse" in hooks
        assert "PostToolUse" in hooks

def test_refresh_preserves_global_hooks():
    with tempfile.TemporaryDirectory() as d:
        _boot(d, "--scope", "global")           # initial global bootstrap
        hooks = _boot(d, "--refresh")           # refresh — must keep global hooks
        assert "SessionStart" in hooks, "refresh stripped SessionStart from global instance"
        assert "Stop" in hooks, "refresh stripped Stop from global instance"

def test_subagent_start_registered_both_scopes():
    import json, subprocess, sys, tempfile
    from pathlib import Path
    SKILL = Path(__file__).resolve().parent.parent
    BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
    for scope_args in (["--scope", "global"], []):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d, *scope_args],
                           capture_output=True, text=True)
            hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
            assert "SubagentStart" in hooks, f"missing for {scope_args}"
            assert "subagent-start-inject.sh" in json.dumps(hooks["SubagentStart"])

def test_read_direction_hooks_registered():
    import json, subprocess, sys, tempfile
    from pathlib import Path
    SKILL = Path(__file__).resolve().parent.parent
    BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d],
                       capture_output=True, text=True)
        hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
        ups = json.dumps(hooks["UserPromptSubmit"])
        assert "remind-context-read.sh" in ups
        assert "remind-capture-decision.sh" in ups  # original preserved
        post = json.dumps(hooks["PostToolUse"])
        assert "post-read-context-gate.sh" in post
        assert "post-edit-validate-and-stale.sh" in post  # original preserved


def test_hooks_for_scope_returns_independent_dicts():
    """Two calls must not share nested mutable objects (no aliasing to module globals)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import bootstrap
    a = bootstrap.hooks_for_scope("project")
    b = bootstrap.hooks_for_scope("project")
    # mutating one must not affect the other or the module globals
    a["PostToolUse"][-1]["hooks"].append({"type": "command", "command": "X"})
    assert b["PostToolUse"][-1]["hooks"] != a["PostToolUse"][-1]["hooks"]
    assert all(h.get("command") != "X" for h in bootstrap._READ_DIRECTION_POST["hooks"])


def test_stop_registers_capture_and_autocommit():
    import json, subprocess, sys, tempfile
    from pathlib import Path
    SKILL = Path(__file__).resolve().parent.parent
    BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d],
                       capture_output=True, text=True)
        hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
        stop = json.dumps(hooks["Stop"])
        assert "capture-on-stop.sh" in stop
        assert "auto-commit-context.sh" in stop
        cfg = json.loads((Path(d) / "context" / "config.json").read_text())
        assert cfg["autoCommitContext"] is True


def test_hook_commands_are_absolute():
    """Hooks must use absolute paths — relative context/hooks/ fails from subdirs."""
    import json, subprocess, sys, tempfile
    from pathlib import Path
    SKILL = Path(__file__).resolve().parent.parent
    BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d],
                       capture_output=True, text=True)
        hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
        cmds = [x["command"] for v in hooks.values() for g in v for x in g.get("hooks", [])]
        ctx_cmds = [c for c in cmds if "context/hooks/" in c]
        assert ctx_cmds, "expected context hooks"
        for c in ctx_cmds:
            assert "bash context/hooks/" not in c, f"relative path leaked: {c}"
            assert f"bash {d}" in c or c.startswith(f"bash {Path(d).resolve()}"), c
