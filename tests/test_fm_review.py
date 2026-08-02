# tests/test_fm_review.py
import json, subprocess, sys, tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "fm-review.py"

def _make_fm(root: Path, projects):
    """projects: list of (name, context_path_or_None_for_dead)"""
    ctx = root / "fm" / "context"; ctx.mkdir(parents=True)
    (ctx / "index.html").write_text("<html><head><title>fm</title></head></html>")
    articles = "".join(
        f'<article class="project">{n} | {p} | desc | active</article>\n'
        for n, p in projects)
    (ctx / "project-registry.html").write_text(
        f"<html><body><section id='projects'>{articles}</section></body></html>")
    return root / "fm"

def test_reports_dead_path():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        fm = _make_fm(root, [("ghost", str(root / "nope" / "context"))])
        r = subprocess.run([sys.executable, str(SCRIPT), "--firstmate", str(fm), "--json"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert any("ghost" in str(x) for x in out["dead_paths"])

def test_skips_self_and_handles_empty():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        fm = _make_fm(root, [])
        r = subprocess.run([sys.executable, str(SCRIPT), "--firstmate", str(fm), "--json"],
                           capture_output=True, text=True)
        assert r.returncode == 0
        out = json.loads(r.stdout)
        assert out["projects"] == [] and out["dead_paths"] == []


def test_validate_timeout_degrades_not_crash(monkeypatch=None):
    """A hanging validate.py must degrade to a status, never crash the run."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import importlib.util
    spec=importlib.util.spec_from_file_location('fm_review', str(Path(__file__).resolve().parent.parent/'scripts'/'fm-review.py'))
    fm_review=importlib.util.module_from_spec(spec); spec.loader.exec_module(fm_review)
    import subprocess
    # Build a project whose validate.py sleeps forever; use a tiny timeout via monkeypatching is overkill —
    # instead assert the function catches TimeoutExpired by simulating it.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ctx = Path(d) / "context"; (ctx / "scripts").mkdir(parents=True)
        (ctx / "scripts" / "validate.py").write_text("import time\ntime.sleep(999)\n")
        orig = subprocess.run
        def fake_run(*a, **k):
            raise subprocess.TimeoutExpired(cmd="validate", timeout=k.get("timeout", 120))
        subprocess.run = fake_run
        try:
            assert fm_review.validate_failures(ctx) == ["timeout"]
        finally:
            subprocess.run = orig
