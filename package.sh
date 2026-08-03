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
PINNED_COMMIT=$(git rev-parse --verify HEAD)
TAG_COMMIT=$(git rev-parse --verify "refs/tags/$TAG^{commit}" 2>/dev/null) || fail "tag does not exist: $TAG"
[ "$TAG_COMMIT" = "$PINNED_COMMIT" ] || fail "tag $TAG does not point at HEAD"
awk -v heading="## [$TAG]" '$0 == heading || index($0, heading " ") == 1 { found=1 } END { exit !found }' CHANGELOG.md 2>/dev/null ||
  fail "CHANGELOG.md has no exact heading for $TAG"

DIST=${DIST_DIR:-dist}
BASE="contarch-$TAG"
DEST="$DIST/$BASE"
[ ! -e "$DEST" ] || fail "release destination already exists: $DEST"

scripts/release-verify.sh

[ -z "$(git status --porcelain=v1 --untracked-files=all)" ] || fail "working tree changed during release verification"
[ "$(git rev-parse --verify HEAD)" = "$PINNED_COMMIT" ] || fail "HEAD changed during release verification"
[ "$(git rev-parse --verify "refs/tags/$TAG^{commit}" 2>/dev/null)" = "$PINNED_COMMIT" ] ||
  fail "tag $TAG changed during release verification"

mkdir -p "$DIST"
BUILD=$(mktemp -d "$DIST/.${BASE}.build.XXXXXX")
trap 'rm -rf "$BUILD"' EXIT
PUBLISH="$BUILD/$BASE"
mkdir "$PUBLISH"
ARCHIVE="$PUBLISH/$BASE.tar.gz"
INSTALLER="$PUBLISH/$BASE.sh"
CHECKSUMS="$PUBLISH/$BASE.sha256"
HEADER="$BUILD/installer-header.sh"

# git archive is the manifest: only bytes committed at the exact tag enter payload.
git archive --format=tar.gz "$PINNED_COMMIT" > "$ARCHIVE"
git show "$PINNED_COMMIT:installer-header.sh" > "$HEADER"
HDR_LINES=$(wc -l < "$HEADER")
sed -e "s/@VERSION@/$TAG/g" -e "s/@LINES@/$((HDR_LINES + 1))/g" "$HEADER" > "$INSTALLER"
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
  (cd "$PUBLISH" && sha256sum "$BASE.sh" "$BASE.tar.gz") > "$CHECKSUMS"
else
  (cd "$PUBLISH" && shasum -a 256 "$BASE.sh" "$BASE.tar.gz") > "$CHECKSUMS"
fi

# GNU mv no-clobber plus the source-remains check makes a destination race fail
# without replacing its bytes. The rename stays on one filesystem.
mv -T -n "$PUBLISH" "$DEST"
[ ! -e "$PUBLISH" ] || fail "release destination appeared during publication: $DEST"
printf 'built %s/%s.{sh,tar.gz,sha256}\n' "$DEST" "$BASE"
