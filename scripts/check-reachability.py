#!/usr/bin/env python3
"""Check bootloader-to-context reachability with BFS."""

import argparse
import json
import sys

from context_utils import check_reachability, find_context_root


def main():
    parser = argparse.ArgumentParser(description="Check context page reachability")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"error": "No context/ directory found"}))
        sys.exit(1)

    result = check_reachability(context_root)
    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"status: {result['status']}")
    print(f"root: {result['root']} fallback={result['fallback_root']}")
    print(f"reachable: {len(result['reachable'])}")
    print(f"orphans: {len(result['orphans'])}")
    print(f"broken_links: {len(result['broken_links'])}")
    if result["orphans"]:
        print("ORPHANS:")
        for page in result["orphans"]:
            print(f"  {page}")
    if result["broken_links"]:
        print("BROKEN LINKS:")
        for item in result["broken_links"]:
            print(f"  {item['from']} -> {item['to']}")


if __name__ == "__main__":
    main()
