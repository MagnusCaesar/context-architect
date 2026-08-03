#!/usr/bin/env bash
# Build verified release artifacts from one exact, clean Git tag.
# Usage: ./package.sh <exact-tag>
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo "release failed: $*" >&2; exit 1; }

[ "$#" -eq 1 ] || fail "usage: ./package.sh <exact-tag>"
TAG=$1
case "$TAG" in
  ""|*[!A-Za-z0-9._-]*) fail "tag must use only A-Z, a-z, 0-9, dot, underscore, or hyphen" ;;
esac

[ -z "$(git status --porcelain=v1 --untracked-files=all)" ] || fail "working tree must be clean, including untracked files"
TAG_COMMIT=$(git rev-parse --verify "refs/tags/$TAG^{commit}" 2>/dev/null) || fail "tag does not exist: $TAG"
HEAD_COMMIT=$(git rev-parse --verify HEAD)
[ "$TAG_COMMIT" = "$HEAD_COMMIT" ] || fail "tag $TAG does not point at HEAD"
awk -v heading="## [$TAG]" '$0 == heading || index($0, heading " ") == 1 { found=1 } END { exit !found }' CHANGELOG.md 2>/dev/null ||
  fail "CHANGELOG.md has no exact heading for $TAG"

python3 scripts/release-verify.py

DIST=${DIST_DIR:-dist}
BUILD=$(mktemp -d "${TMPDIR:-/tmp}/contarch-release.XXXXXX")
trap 'rm -rf "$BUILD"' EXIT
BASE="contarch-$TAG"
ARCHIVE="$BUILD/$BASE.tar.gz"
INSTALLER="$BUILD/$BASE.sh"
CHECKSUMS="$BUILD/$BASE.sha256"

# git archive is the manifest: only bytes committed at the exact tag enter payload.
git archive --format=tar.gz "$TAG" > "$ARCHIVE"
HDR_LINES=$(wc -l < installer-header.sh)
sed -e "s/@VERSION@/$TAG/g" -e "s/@LINES@/$((HDR_LINES + 1))/g" installer-header.sh > "$INSTALLER"
cat "$ARCHIVE" >> "$INSTALLER"
chmod +x "$INSTALLER"

python3 scripts/release-verify.py --archive "$ARCHIVE" --installer "$INSTALLER" --tag "$TAG"

DRY_HOME="$BUILD/dry-home"
mkdir "$DRY_HOME"
for platform in claude codex both; do
  HOME="$DRY_HOME" sh "$INSTALLER" --platform "$platform" --dry-run >/dev/null
  [ -z "$(find "$DRY_HOME" -mindepth 1 -print -quit)" ] || fail "$platform dry run changed HOME"
done

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$BUILD" && sha256sum "$BASE.sh" "$BASE.tar.gz") > "$CHECKSUMS"
else
  (cd "$BUILD" && shasum -a 256 "$BASE.sh" "$BASE.tar.gz") > "$CHECKSUMS"
fi

mkdir -p "$DIST"
mv "$INSTALLER" "$ARCHIVE" "$CHECKSUMS" "$DIST/"
printf 'built %s/%s.{sh,tar.gz,sha256}\n' "$DIST" "$BASE"
