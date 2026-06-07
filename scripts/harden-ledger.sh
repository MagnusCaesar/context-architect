#!/usr/bin/env bash
set -euo pipefail

context_dir="${1:-context}"
if [[ ! -d "$context_dir" && -f "ledger.html" ]]; then
  context_dir="."
fi

if [[ ! -d "$context_dir" ]]; then
  printf '{"status":"error","reason":"context directory not found","path":"%s"}\n' "$context_dir"
  exit 1
fi

path="$context_dir/ledger-events.ndjson"
: >> "$path"

if [[ "$(uname -s)" != "Linux" ]]; then
  printf '{"status":"unsupported","reason":"not_linux","path":"%s"}\n' "$path"
  exit 0
fi

if ! command -v chattr >/dev/null 2>&1; then
  printf '{"status":"unsupported","reason":"chattr_not_found","path":"%s"}\n' "$path"
  exit 0
fi

if chattr +a "$path" >/dev/null 2>&1; then
  printf '{"status":"hardened","mode":"append_only","path":"%s"}\n' "$path"
else
  printf '{"status":"unsupported","reason":"chattr_failed","path":"%s"}\n' "$path"
fi
