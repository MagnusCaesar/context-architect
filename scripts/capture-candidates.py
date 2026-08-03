#!/usr/bin/env python3
"""capture-candidates.py — append a captured candidate to capture-inbox.html.

Level-2 capture: writes ONLY to the inbox, never to the live decisions/
failure-todos/open-questions graph. Dedupes against existing pending entries.
"""
import argparse, sys
from pathlib import Path

from context_utils import CAPTURE_KINDS, append_capture_candidate, firstmate_root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default=str(firstmate_root() / "context" / "capture-inbox.html"))
    ap.add_argument("--summary", required=True)
    ap.add_argument("--kind", required=True, choices=sorted(CAPTURE_KINDS))
    ap.add_argument("--source", default="")
    args = ap.parse_args()

    inbox = Path(args.inbox)
    if not inbox.exists():
        print(f"inbox not found: {inbox}", file=sys.stderr)
        sys.exit(1)

    if not append_capture_candidate(inbox.parent, args.summary, args.kind, args.source):
        print("duplicate pending candidate; skipped", file=sys.stderr)

if __name__ == "__main__":
    main()
