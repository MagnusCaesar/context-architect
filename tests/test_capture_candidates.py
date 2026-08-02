# tests/test_capture_candidates.py
import subprocess, sys, tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "capture-candidates.py"

INBOX_SEED = """<html><body>
<section id="candidates">
</section>
</body></html>
"""

def _add(inbox, summary, kind="decision"):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--inbox", str(inbox),
         "--summary", summary, "--kind", kind, "--source", "sess-1"],
        capture_output=True, text=True)

def test_appends_candidate():
    with tempfile.TemporaryDirectory() as d:
        inbox = Path(d) / "capture-inbox.html"
        inbox.write_text(INBOX_SEED)
        _add(inbox, "store timing paths in sqlite")
        html = inbox.read_text()
        assert "store timing paths in sqlite" in html
        assert 'data-kind="decision"' in html
        assert 'data-status="pending"' in html

def test_dedupes_pending():
    with tempfile.TemporaryDirectory() as d:
        inbox = Path(d) / "capture-inbox.html"
        inbox.write_text(INBOX_SEED)
        _add(inbox, "store timing paths in sqlite")
        _add(inbox, "store timing paths in SQLite")  # case/space variant
        assert inbox.read_text().count('class="candidate"') == 1

def test_summary_with_html_is_escaped_in_body():
    with tempfile.TemporaryDirectory() as d:
        inbox = Path(d) / "capture-inbox.html"
        inbox.write_text(INBOX_SEED)
        _add(inbox, "</article><article>evil", kind="decision")
        html_text = inbox.read_text()
        # Body text (between > and </article>) must have the raw HTML escaped.
        # Extract body content after the opening tag close.
        import re as _re
        m = _re.search(r'<article class="candidate"[^>]*>(.*?)</article>', html_text, _re.S)
        assert m is not None, "expected one candidate article"
        body = m.group(1)
        assert "</article>" not in body
        assert "&lt;" in body

def test_rejects_bad_kind():
    with tempfile.TemporaryDirectory() as d:
        inbox = Path(d) / "capture-inbox.html"
        inbox.write_text(INBOX_SEED)
        r = _add(inbox, "x", kind="bogus")
        assert r.returncode != 0

def test_dedupes_pending_with_quotes():
    with tempfile.TemporaryDirectory() as d:
        inbox = Path(d) / "capture-inbox.html"
        inbox.write_text(INBOX_SEED)
        _add(inbox, 'use "sqlite" for paths')
        _add(inbox, 'use "sqlite" for paths')  # exact duplicate with quotes
        assert inbox.read_text().count('class="candidate"') == 1

def _add_with_source(inbox, summary, source, kind="decision"):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--inbox", str(inbox),
         "--summary", summary, "--kind", kind, "--source", source],
        capture_output=True, text=True)

def test_source_with_html_is_escaped():
    with tempfile.TemporaryDirectory() as d:
        inbox = Path(d) / "capture-inbox.html"
        inbox.write_text(INBOX_SEED)
        _add_with_source(inbox, "a decision", 'sess">evil')
        html_text = inbox.read_text()
        assert html_text.count('class="candidate"') == 1
        assert '">evil' not in html_text  # raw break-out must not appear
        # escaped form must appear in the data-source attribute
        import re as _re
        m = _re.search(r'data-source="([^"]*)"', html_text)
        assert m is not None
        assert "&gt;" in m.group(1) or "&quot;" in m.group(1)
