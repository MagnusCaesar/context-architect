import sys, pathlib, importlib.util
base = pathlib.Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("te", base / "test-enforcement.py")
te = importlib.util.module_from_spec(spec); spec.loader.exec_module(te)

def test_score_counts_non_edits():
    verdicts = [{"edited": False}, {"edited": True}, {"edited": False}, {"edited": False}]
    assert te.score(verdicts) == 0.75

def test_prompts_cover_known_bypasses():
    assert len(te.PROMPTS) >= 3
    joined = " ".join(te.PROMPTS).lower()
    assert "handle it" in joined        # compound-sentence bypass
