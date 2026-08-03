#!/usr/bin/env bash
# context-architecture skill installer @VERSION@ (self-extracting; tarball appended below)
# Usage: sh THIS_FILE [--platform claude|codex|both] [--dry-run]
set -euo pipefail

SKILL=context-architecture
VERSION=@VERSION@
PAYLOAD_LINE=@LINES@
PLATFORM=
TARGETS=()
DRY=

while [ "$#" -gt 0 ]; do
  case "$1" in
    --platform)
      [ "$#" -gt 1 ] || { echo "--platform needs claude, codex, or both" >&2; exit 2; }
      PLATFORM=$2; shift 2 ;;
    --claude-only) PLATFORM=claude; shift ;;
    --codex-only)  PLATFORM=codex; shift ;;
    --dry-run)     DRY=1; shift ;;
    -h|--help)     sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$PLATFORM" in
  claude) TARGETS=("$HOME/.claude/skills") ;;
  codex)  TARGETS=("$HOME/.codex/skills") ;;
  both)   TARGETS=("$HOME/.claude/skills" "$HOME/.codex/skills") ;;
  "") echo "choose --platform claude|codex|both" >&2; exit 2 ;;
  *) echo "--platform must be claude, codex, or both" >&2; exit 2 ;;
esac

if [ -n "$DRY" ]; then
  for root in "${TARGETS[@]}"; do
    echo "would install -> $root/$SKILL"
  done
  exit 0
fi

command -v python3 >/dev/null || { echo "python3 required" >&2; exit 1; }
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
tail -n +"$PAYLOAD_LINE" "$0" | tar xzf - -C "$STAGE"
# The installer must not ship its own build tooling into the install.
rm -f "$STAGE/package.sh" "$STAGE/installer-header.sh"
printf '%s\n' "$VERSION" > "$STAGE/VERSION"

for root in "${TARGETS[@]}"; do
  dest="$root/$SKILL"
  mkdir -p "$root"
  # Replace, but keep the previous copy recoverable: this skill's own repo may live here.
  if [ -e "$dest" ]; then
    bak="$dest.bak-$(date +%Y%m%d%H%M%S)"
    mv "$dest" "$bak"
    echo "existing install moved to $bak"
  fi
  cp -R "$STAGE" "$dest"
  chmod +x "$dest"/hooks/*.sh "$dest"/scripts/*.py "$dest"/scripts/*.sh "$dest"/smoke.sh 2>/dev/null || true
  echo "installed $SKILL $VERSION -> $dest"
done

cat <<EOF

Next: bootstrap a project with
  python3 "${TARGETS[0]}/$SKILL/scripts/bootstrap.py" --target /path/to/project --scan
EOF
exit 0
# ---- payload below this line; do not edit ----
