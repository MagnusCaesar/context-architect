import json, subprocess, sys, tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"

def _boot(target, *extra):
    subprocess.run([sys.executable, str(BOOTSTRAP), "--target", str(target), "--platform", "claude", *extra],
                   capture_output=True, text=True)
    return json.loads((Path(target) / ".claude" / "settings.json").read_text())["hooks"]

def test_global_registers_sessionstart_and_stop():
    with tempfile.TemporaryDirectory() as d:
        hooks = _boot(d, "--scope", "global")
        assert "SessionStart" in hooks
        assert "Stop" in hooks
        ss = json.dumps(hooks["SessionStart"])
        assert "hook_dispatch.py" in ss
        assert "--event Stop" in json.dumps(hooks["Stop"])

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
            subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d, "--platform", "claude", *scope_args],
                           capture_output=True, text=True)
            hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
            assert "SubagentStart" in hooks, f"missing for {scope_args}"
            assert "--event SubagentStart" in json.dumps(hooks["SubagentStart"])

def test_read_direction_hooks_registered():
    import json, subprocess, sys, tempfile
    from pathlib import Path
    SKILL = Path(__file__).resolve().parent.parent
    BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d, "--platform", "claude"],
                       capture_output=True, text=True)
        hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
        ups = json.dumps(hooks["UserPromptSubmit"])
        assert "--event UserPromptSubmit" in ups
        post = json.dumps(hooks["PostToolUse"])
        assert "--event PostToolUse" in post
        assert "Read" in post


def test_stop_registers_canonical_dispatcher():
    import json, subprocess, sys, tempfile
    from pathlib import Path
    SKILL = Path(__file__).resolve().parent.parent
    BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d, "--platform", "claude"],
                       capture_output=True, text=True)
        hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
        stop = json.dumps(hooks["Stop"])
        assert "--event Stop" in stop


def test_hook_commands_are_absolute():
    """Dispatcher commands must be absolute so hooks work from subdirectories."""
    import json, subprocess, sys, tempfile
    from pathlib import Path
    SKILL = Path(__file__).resolve().parent.parent
    BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(BOOTSTRAP), "--target", d, "--platform", "claude"],
                       capture_output=True, text=True)
        hooks = json.loads((Path(d) / ".claude" / "settings.json").read_text())["hooks"]
        cmds = [x["command"] for v in hooks.values() for g in v for x in g.get("hooks", [])]
        ctx_cmds = [c for c in cmds if "context/scripts/hook_dispatch.py" in c]
        assert ctx_cmds, "expected dispatcher hooks"
        for c in ctx_cmds:
            assert "python3 /" in c, f"relative path leaked: {c}"
            assert str(Path(d).resolve()) in c, c
