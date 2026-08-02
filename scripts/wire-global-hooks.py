#!/usr/bin/env python3
"""wire-global-hooks.py -- idempotently add first-mate SessionStart hook to a
user-global settings.json, preserving all existing hooks.
Note: SubagentStart is registered per-project only (portable with the project)."""
import argparse, json, os
from pathlib import Path

def ensure(hooks: dict, event: str, command: str) -> None:
    entries = hooks.setdefault(event, [])
    for group in entries:
        for h in group.get("hooks", []):
            if h.get("command") == command:
                return  # already present
    entries.append({"hooks": [{"type": "command", "command": command}]})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", required=True)
    ap.add_argument("--firstmate", default=os.path.expanduser("~/.claude/firstmate"))
    args = ap.parse_args()

    p = Path(args.settings)
    data = json.loads(p.read_text()) if p.exists() else {}
    hooks = data.setdefault("hooks", {})
    fm = args.firstmate.rstrip("/")
    ensure(hooks, "SessionStart", f"bash {fm}/context/hooks/session-start-inject.sh")
    # Atomic write: a kill mid-write must never truncate a live settings.json.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)

if __name__ == "__main__":
    main()
