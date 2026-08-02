import sys, pathlib, importlib.util
base = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(base))
spec = importlib.util.spec_from_file_location("cf", base / "check-freshness.py")
cf = importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)

def test_drift_detected(tmp_path):
    page = tmp_path / "vendored.html"
    page.write_text('<meta name="vendored-commit" content="abc123">\n'
                    '<meta name="vendored-source" content="upstream/sub">')
    warns = cf.check_vendored_drift(tmp_path, current_commits={"upstream/sub": "def456"})
    assert any("abc123" in w and "def456" in w for w in warns)

def test_no_drift_when_match(tmp_path):
    page = tmp_path / "vendored.html"
    page.write_text('<meta name="vendored-commit" content="abc123">\n'
                    '<meta name="vendored-source" content="upstream/sub">')
    warns = cf.check_vendored_drift(tmp_path, current_commits={"upstream/sub": "abc123"})
    assert warns == []
