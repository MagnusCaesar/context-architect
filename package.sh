#!/usr/bin/env bash
# Build a single self-extracting installer for this skill.
# Usage: ./package.sh [outfile]   (default: dist/contarch-<sha>.sh)
set -euo pipefail
cd "$(dirname "$0")"

VER=$(git describe --always --dirty)
OUT=${1:-dist/contarch-$VER.sh}
mkdir -p "$(dirname "$OUT")"

# ponytail: git ls-files is the manifest -- .gitignore already excludes __pycache__/*.pyc,
# so there is no separate include list to keep in sync. Working tree, not HEAD, so
# uncommitted skill edits still package.
TAR=$(mktemp); trap 'rm -f "$TAR"' EXIT
git ls-files -co --exclude-standard -z | tar czf "$TAR" --null -T -

HDR_LINES=$(wc -l < installer-header.sh)
{
  sed -e "s/@VERSION@/$VER/" -e "s/@LINES@/$((HDR_LINES + 1))/" installer-header.sh
  cat "$TAR"
} > "$OUT"
cp "$TAR" "${OUT%.sh}.tar.gz"
chmod +x "$OUT"

printf 'built %s (%s)\n' "$OUT" "$(du -h "$OUT" | cut -f1)"
printf 'built %s (%s)\n' "${OUT%.sh}.tar.gz" "$(du -h "${OUT%.sh}.tar.gz" | cut -f1)"
