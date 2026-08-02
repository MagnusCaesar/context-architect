# tests/test_wire_global_hooks.py
import json, subprocess, sys, tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "wire-global-hooks.py"

EXISTING = {"hooks": {"SessionStart": [
    {"hooks": [{"type": "command", "command": "/existing/cache-heal.mjs"}]}
]}}

def _run(settings, fm):
    return subprocess.run([sys.executable, str(SCRIPT), "--settings", str(settings),
                           "--firstmate", fm], capture_output=True, text=True)

def test_appends_and_preserves():
    with tempfile.TemporaryDirectory() as d:
        s = Path(d) / "settings.json"; s.write_text(json.dumps(EXISTING))
        _run(s, "/fm")
        h = json.loads(s.read_text())["hooks"]
        ss = json.dumps(h["SessionStart"])
        assert "/existing/cache-heal.mjs" in ss          # preserved
        assert "session-start-inject.sh" in ss           # appended
        assert "SubagentStart" not in h                  # not added by this script

def test_idempotent():
    with tempfile.TemporaryDirectory() as d:
        s = Path(d) / "settings.json"; s.write_text(json.dumps(EXISTING))
        _run(s, "/fm"); _run(s, "/fm")
        h = json.loads(s.read_text())["hooks"]
        assert json.dumps(h["SessionStart"]).count("session-start-inject.sh") == 1
        assert "SubagentStart" not in h                  # still not added after re-run
        assert "/existing/cache-heal.mjs" in json.dumps(h["SessionStart"])  # preserved across re-run
