#!/usr/bin/env python3
"""Bounded-mutex tests for context_utils.context_mutex + start-task.py.

Proves: (1) uncontended acquire is fast, (2) a contended mutex fails LOUD with
MutexTimeout at the config ceiling instead of hanging, (3) start-task.py returns
valid JSON with a blocked status under contention rather than crashing/hanging.

Run: python3 test_bounded_mutex.py   (stdlib unittest, no framework)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SCRIPTS)

from context_utils import context_mutex, MutexTimeout  # noqa: E402

HOLDER = (
    "import sys,time\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from pathlib import Path\n"
    "from context_utils import context_mutex\n"
    "with context_mutex(Path(sys.argv[2]), sys.argv[3]):\n"
    "    print('HELD', flush=True)\n"
    "    time.sleep(20)\n"
)


def make_ctx(mutex_timeout=2, default_role="orchestrator"):
    tmp = Path(tempfile.mkdtemp(prefix="ctxmutex-"))
    ctx = tmp / "context"
    (ctx / ".locks").mkdir(parents=True)
    (ctx / "index.html").write_text("<html><head></head><body></body></html>")
    (ctx / "config.json").write_text(
        json.dumps({"lockMutexTimeoutSec": mutex_timeout, "defaultRole": default_role})
    )
    return tmp, ctx


class TestBoundedMutex(unittest.TestCase):
    def test_1_uncontended_fast(self):
        """PASS: acquire+release, second acquire after release succeeds fast (<1s)."""
        tmp, ctx = make_ctx()
        try:
            with context_mutex(ctx, "context"):
                pass  # acquired + released
            start = time.monotonic()
            with context_mutex(ctx, "context"):
                pass
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 1.0, f"second acquire too slow: {elapsed:.2f}s")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_2_contended_fails_bounded(self):
        """FAILURE MODE: holder keeps mutex 20s; ceiling=2s -> MutexTimeout in ~2s."""
        tmp, ctx = make_ctx(mutex_timeout=2)
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER, SCRIPTS, str(ctx), "context"],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(holder.stdout.readline().strip(), "HELD", "holder never acquired")
            start = time.monotonic()
            with self.assertRaises(MutexTimeout):
                with context_mutex(ctx, "context"):
                    pass
            elapsed = time.monotonic() - start
            # bounded-fail, not a hang: ~2s ceiling
            self.assertGreater(elapsed, 1.8, f"failed too early: {elapsed:.2f}s")
            self.assertLess(elapsed, 4.0, f"hung instead of bounded: {elapsed:.2f}s")
        finally:
            holder.terminate()
            holder.wait(timeout=5)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_3_start_task_blocked_json(self):
        """start-task.py under contention returns valid JSON with a blocked status."""
        tmp, ctx = make_ctx(mutex_timeout=2)
        page = ctx / "dummy.html"
        page.write_text(
            '<html><head>'
            '<meta name="locked" content="true">'
            '<meta name="locked-by" content="other-agent">'
            '<meta name="locked-at" content="2026-07-07T00:00:00Z">'
            '</head><body></body></html>'
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER, SCRIPTS, str(ctx), "lock-dummy.html"],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(holder.stdout.readline().strip(), "HELD", "holder never acquired")
            proc = subprocess.run(
                [sys.executable, str(Path(SCRIPTS) / "start-task.py"),
                 "--page", "dummy.html", "--agent-id", "worker-2",
                 "--intent", "test"],
                cwd=str(tmp), capture_output=True, text=True, timeout=15,
            )
            self.assertTrue(proc.stdout.strip(), f"empty output; stderr={proc.stderr}")
            data = json.loads(proc.stdout)  # must be valid JSON, not a crash
            self.assertEqual(data.get("status"), "blocked_lock_busy", data)
            self.assertFalse(data.get("lock_status", {}).get("acquired", True), data)
        finally:
            holder.terminate()
            holder.wait(timeout=5)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
