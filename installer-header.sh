#!/usr/bin/env bash
# context-architecture skill installer @VERSION@ (self-extracting; tarball appended below)
# Usage: sh THIS_FILE [--claude-only|--codex-only] [--dry-run]
set -euo pipefail

SKILL=context-architecture
VERSION=@VERSION@
PAYLOAD_LINE=@LINES@
TARGETS=("$HOME/.claude/skills" "$HOME/.codex/skills")
DRY=

for a in "$@"; do
  case "$a" in
    --claude-only) TARGETS=("$HOME/.claude/skills") ;;
    --codex-only)  TARGETS=("$HOME/.codex/skills") ;;
    --dry-run)     DRY=1 ;;
    -h|--help)     sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 required" >&2; exit 1; }

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
tail -n +"$PAYLOAD_LINE" "$0" | tar xzf - -C "$STAGE"
# The installer must not ship its own build tooling into the install.
rm -f "$STAGE/package.sh" "$STAGE/installer-header.sh"
printf '%s\n' "$VERSION" > "$STAGE/VERSION"

for root in "${TARGETS[@]}"; do
  dest="$root/$SKILL"
  if [ -n "$DRY" ]; then echo "would install -> $dest"; continue; fi
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

[ -n "$DRY" ] && exit 0
cat <<EOF

Next: bootstrap a project with
  python3 "${TARGETS[0]}/$SKILL/scripts/bootstrap.py" --target /path/to/project --scan
EOF
exit 0
# ---- payload below this line; do not edit ----
