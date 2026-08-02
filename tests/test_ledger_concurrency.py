# tests/test_ledger_concurrency.py
# Concurrency guard for the shared active-locks ledger write.
# Fails on pre-fix code (lost updates); passes once add_active_lock serializes.
import sys, re, multiprocessing as mp
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

from context_utils import add_active_lock, append_ledger_event  # noqa: E402

LEDGER_SEED = """<html><body>
<section id="active-locks"><table><tbody>
</tbody></table></section>
</body></html>
"""

def _worker(args):
    root, i = args
    add_active_lock(Path(root), f"page{i}.html", f"agent{i}")

def test_concurrent_add_active_lock_no_lost_rows(tmp="/tmp/ledger-conc-test"):
    root = Path(tmp)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".locks").mkdir(exist_ok=True)
    (root / "ledger.html").write_text(LEDGER_SEED)
    n = 16
    with mp.Pool(n) as p:
        p.map(_worker, [(str(root), i) for i in range(n)])
    rows = re.findall(r"<tr>", (root / "ledger.html").read_text())
    assert len(rows) == n, f"expected {n} rows, got {len(rows)} (lost updates = race)"


def _mixed_worker(args):
    # Each worker adds an active-lock row AND appends a ledger event. The event
    # append triggers render_ledger_events, which rewrites ledger.html — the
    # cross-writer path that raced with add_active_lock's row write.
    root, i = args
    r = Path(root)
    add_active_lock(r, f"mix{i}.html", f"agent{i}")
    append_ledger_event(r, "acquire", f"mix{i}.html", f"agent{i}", "acquired", "x", trigger_hygiene=False)

def test_concurrent_add_vs_render_no_lost_active_rows(tmp="/tmp/ledger-mixed-test"):
    root = Path(tmp)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".locks").mkdir(exist_ok=True)
    (root / "ledger.html").write_text(LEDGER_SEED)
    n = 16
    with mp.Pool(n) as p:
        p.map(_mixed_worker, [(str(root), i) for i in range(n)])
    # Every worker's active-lock row must survive the concurrent render rewrites.
    html = (root / "ledger.html").read_text()
    active = re.search(r'<section id="active-locks">.*?<tbody>(.*?)</tbody>', html, re.S)
    active_rows = re.findall(r"<tr>", active.group(1)) if active else []
    assert len(active_rows) == n, (
        f"expected {n} active-lock rows, got {len(active_rows)} "
        f"(render_ledger_events clobbered active rows = cross-writer race)")

if __name__ == "__main__":
    test_concurrent_add_active_lock_no_lost_rows()
    test_concurrent_add_vs_render_no_lost_active_rows()
    print("PASS")
