#!/usr/bin/env python3
"""Run once-per-day context hygiene through ledger events."""

import argparse
import json
import sys

from context_utils import find_context_root, run_daily_hygiene


def main():
    parser = argparse.ArgumentParser(description="Run daily context hygiene")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        result = {"error": "No context/ directory found"}
        if not args.quiet:
            print(json.dumps(result, indent=2))
        sys.exit(1)

    result = run_daily_hygiene(context_root, append_event=True)
    if args.quiet:
        return
    print(json.dumps(result, indent=2) if args.json else f"status: {result['status']}")


if __name__ == "__main__":
    main()
