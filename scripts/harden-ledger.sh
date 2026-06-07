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

context_real=$(cd "$context_dir" && pwd -P)
path="$context_real/ledger-events.ndjson"
if [[ -L "$path" ]]; then
  printf '{"status":"error","reason":"ledger path is symlink","path":"%s"}\n' "$path"
  exit 1
fi
: >> "$path"
path_real=$(readlink -f "$path")
case "$path_real" in
  "$context_real"/*) ;;
  *)
    printf '{"status":"error","reason":"ledger path escapes context","path":"%s"}\n' "$path_real"
    exit 1
    ;;
esac

if [[ "$(uname -s)" != "Linux" ]]; then
  printf '{"status":"unsupported","reason":"not_linux","path":"%s"}\n' "$path"
  exit 0
fi

if ! command -v chattr >/dev/null 2>&1; then
  printf '{"status":"unsupported","reason":"chattr_not_found","path":"%s"}\n' "$path"
  exit 0
fi

if chattr +a "$path_real" >/dev/null 2>&1; then
  printf '{"status":"hardened","mode":"append_only","boundary":"unverified","path":"%s"}\n' "$path_real"
else
  printf '{"status":"unsupported","reason":"chattr_failed","path":"%s"}\n' "$path_real"
fi
