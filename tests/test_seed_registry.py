import subprocess, sys, tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "seed-registry.py"

def test_finds_context_dirs():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        proj = root / "alpha" / "context"
        proj.mkdir(parents=True)
        (proj / "index.html").write_text("<html><head><title>alpha ctx</title></head></html>")
        (root / "beta").mkdir()  # no context -> ignored
        r = subprocess.run([sys.executable, str(SCRIPT), "--roots", str(root)],
                           capture_output=True, text=True)
        assert r.returncode == 0
        assert "alpha" in r.stdout
        assert str(proj) in r.stdout
        assert "beta" not in r.stdout
