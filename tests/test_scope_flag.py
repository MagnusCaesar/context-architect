import json, subprocess, sys, tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"

def _run(target, *extra):
    return subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--target", str(target), *extra],
        capture_output=True, text=True)

def test_scope_global_writes_scope_key():
    with tempfile.TemporaryDirectory() as d:
        _run(d, "--scope", "global")
        cfg = json.loads((Path(d) / "context" / "config.json").read_text())
        assert cfg["scope"] == "global"

def test_scope_project_is_default_and_marked():
    with tempfile.TemporaryDirectory() as d:
        _run(d)  # no --scope
        cfg = json.loads((Path(d) / "context" / "config.json").read_text())
        assert cfg["scope"] == "project"

def test_invalid_scope_rejected():
    with tempfile.TemporaryDirectory() as d:
        r = _run(d, "--scope", "bogus")
        assert r.returncode != 0
        assert "scope" in (r.stderr + r.stdout).lower()
