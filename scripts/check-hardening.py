#!/usr/bin/env python3
"""Report runtime hardening state without changing files."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from context_utils import find_context_root


DENIED_COMMANDS = ["rm", "chmod", "chown", "chattr", "setfacl", "sudo", "dd", "truncate"]


def is_append_only(path: Path) -> bool | None:
    if not path.exists() or shutil.which("lsattr") is None:
        return None
    try:
        result = subprocess.run(["lsattr", "-d", str(path)], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    flags = result.stdout.split()[0]
    return "a" in flags


def main():
    parser = argparse.ArgumentParser(description="Check context hardening state")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"status": "error", "reason": "No context/ directory found"}))
        sys.exit(1)

    ledger = context_root / "ledger-events.ndjson"
    security = context_root / "security.json"
    config = context_root / "config.json"
    scripts = context_root / "scripts"
    append_only = is_append_only(ledger)
    dangerous_on_path = [cmd for cmd in DENIED_COMMANDS if shutil.which(cmd)]
    protected_writable = [
        str(path.relative_to(context_root))
        for path in [ledger, security if security.exists() else config]
        if path.exists() and os.access(path, os.W_OK)
    ]
    protected_parent_writable = [
        str(path.parent.relative_to(context_root))
        for path in [ledger, security if security.exists() else config]
        if path.exists() and os.access(path.parent, os.W_OK)
    ]
    scripts_writable = scripts.exists() and os.access(scripts, os.W_OK)

    warnings = []
    if append_only is not True:
        warnings.append("ledger-events.ndjson is not append-only for this process")
    if protected_writable:
        warnings.append("protected authority files are writable by this process")
    if protected_parent_writable:
        warnings.append("protected authority parent directories are writable by this process")
    if scripts_writable:
        warnings.append("context/scripts is writable by this process")
    if "chattr" in dangerous_on_path:
        warnings.append("chattr is available to this process; sandbox should deny chattr -a")

    result = {
        "status": "ok" if not warnings else "unhardened",
        "ledger_append_only": append_only,
        "protected_writable": protected_writable,
        "protected_parent_writable": protected_parent_writable,
        "scripts_writable": scripts_writable,
        "dangerous_commands_on_path": dangerous_on_path,
        "required_external_boundary": "Run hardening as root, an elevated user, or another Unix user that the agent cannot control.",
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"status: {result['status']}")
        for warning in warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
