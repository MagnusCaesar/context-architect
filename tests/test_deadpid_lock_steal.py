# tests/test_deadpid_lock_steal.py
# Regression guard for the dead-PID lock-steal bug.
#
# write_pid_sentinel() stored os.getppid() (the ephemeral per-invocation shell),
# which dies the moment start-task returns. So _owner_process_alive() read "dead"
# for essentially every live lock, letting a sibling agent STEAL it via the
# dead-PID paths in contention_break_allowed() and reap_stale_locks().
#
# Fix: stop gating steal/reap on the dead-PID signal. Rely on heartbeat staleness
# (contention) and the global idle timeout (reap). These tests pin that behavior.
#
# Run: python3 tests/test_deadpid_lock_steal.py   (stdlib unittest, self-cleaning)
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

from context_utils import contention_break_allowed, reap_stale_locks  # noqa: E402

DEAD_PID = 2**31 - 1  # never a live process; os.kill(pid, 0) -> ProcessLookupError

LEDGER_TMPL = """<html><head></head><body>
<section id="active-locks"><table><tbody>
          <tr><td>{page}</td><td>{agent}</td><td>{locked_at}</td><td>start-task</td></tr>
</tbody></table></section>
</body></html>
"""

PAGE_TMPL = '<html><head><meta name="locked" content="true">' \
            '<meta name="locked-by" content="{agent}">' \
            '<meta name="locked-at" content="{locked_at}"></head><body></body></html>\n'


def _mk_context(idle_minutes=5, contention_minutes=3):
    root = Path(tempfile.mkdtemp(prefix="deadpid-"))
    (root / ".locks").mkdir()
    (root / "config.json").write_text(json.dumps({
        "defaultRole": "worker",
        "contentionBreakMinutes": contention_minutes,
        "autoReleaseIdleMinutes": idle_minutes,
    }))
    return root


def _write_hb(root, agent, age_minutes):
    hb = root / ".locks" / f"hb-{agent}"
    hb.write_text("0")
    t = time.time() - age_minutes * 60
    os.utime(hb, (t, t))


def _write_dead_pid(root, page):
    (root / ".locks" / f"pid-{page.replace('/', '_')}").write_text(str(DEAD_PID))


def _iso(age_minutes):
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ContentionBreak(unittest.TestCase):
    """contention_break_allowed: only heartbeat staleness may authorize a steal."""

    def _root(self):
        r = _mk_context()
        self.addCleanup(lambda: __import__("shutil").rmtree(r, ignore_errors=True))
        return r

    def test_fresh_heartbeat_blocks_steal(self):
        # Owner heartbeat is fresh + PID dead -> sibling MUST be blocked.
        r = self._root()
        _write_hb(r, "owner", age_minutes=0)
        _write_dead_pid(r, "decisions.html")
        self.assertFalse(contention_break_allowed(r, "decisions.html", "owner"))

    def test_stale_heartbeat_allows_break(self):
        # Legit staleness break preserved: heartbeat older than contentionBreakMinutes.
        r = self._root()
        _write_hb(r, "owner", age_minutes=10)  # > 3
        _write_dead_pid(r, "decisions.html")
        self.assertTrue(contention_break_allowed(r, "decisions.html", "owner"))

    def test_no_heartbeat_dead_pid_blocks_steal(self):
        # THE BUG: start-task -> first-edit window has no heartbeat yet + dead PID.
        # Old code returned True (steal). Must now be False.
        r = self._root()
        _write_dead_pid(r, "decisions.html")  # no hb file at all
        self.assertFalse(contention_break_allowed(r, "decisions.html", "owner"))


class ReapStaleLocks(unittest.TestCase):
    """reap_stale_locks: only the global idle timeout may reap; dead PID must not."""

    def _root(self, idle_minutes, locked_age_minutes):
        r = _mk_context(idle_minutes=idle_minutes)
        self.addCleanup(lambda: __import__("shutil").rmtree(r, ignore_errors=True))
        locked_at = _iso(locked_age_minutes)
        (r / "ledger.html").write_text(
            LEDGER_TMPL.format(page="decisions.html", agent="owner", locked_at=locked_at))
        page = r / "decisions.html"
        page.write_text(PAGE_TMPL.format(agent="owner", locked_at=locked_at))
        # Align page mtime with lock age so max(activity) reflects the intended age.
        t = time.time() - locked_age_minutes * 60
        os.utime(page, (t, t))
        _write_dead_pid(r, "decisions.html")  # dead PID present but must be ignored
        return r

    def test_recent_lock_not_reaped(self):
        # Dead PID + recent lock (< idle window). Old code released via
        # owner_process_dead; must now be kept.
        r = self._root(idle_minutes=5, locked_age_minutes=0)
        self.assertEqual(reap_stale_locks(r), [])

    def test_idle_lock_reaped(self):
        # Lock idle past autoReleaseIdleMinutes -> Check 2 still reaps it.
        r = self._root(idle_minutes=5, locked_age_minutes=30)
        reaped = reap_stale_locks(r)
        self.assertEqual([x["page"] for x in reaped], ["decisions.html"])
        self.assertEqual(reaped[0]["reason"], "idle_timeout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
