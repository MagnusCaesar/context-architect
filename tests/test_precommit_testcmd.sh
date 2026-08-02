#!/usr/bin/env bash
# Verifies the testCmd pre-commit gate: unset->ok, failing->abort+message, passing->ok, --no-verify->ok.
set -u
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$SKILL/hooks/pre-commit"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# A context project: config.json lives in the repo root (so CONTEXT_DIR resolves to $TOP).
mk_repo() {  # $1 = testCmd value (may be empty)
  rm -rf "$TMP/p"; mkdir -p "$TMP/p/scripts"; cd "$TMP/p"
  echo '<html><head><title>x</title></head><body></body></html>' > index.html
  printf '{"projectName":"p","testCmd":"%s"}' "$1" > config.json
  # minimal validate.py that always passes, so the validate block never interferes
  printf 'import sys\nsys.exit(0)\n' > scripts/validate.py
  git init -q .; cp "$HOOK" .git/hooks/pre-commit; chmod +x .git/hooks/pre-commit
  git add -A
}

# Case A: testCmd unset -> commit succeeds
mk_repo ""
git commit -q -m init && echo "A ok" || { echo "FAIL A: unset testCmd blocked commit"; exit 1; }

# Case B: testCmd fails -> commit aborts, message shows tail + --no-verify
mk_repo "sh -c 'echo FAILED test_x; exit 1'"
OUT="$(git commit -m init 2>&1)"; RC=$?
[ $RC -ne 0 ] || { echo "FAIL B: failing testCmd did NOT block"; exit 1; }
echo "$OUT" | grep -q -- "--no-verify" || { echo "FAIL B: no escape hatch in message"; exit 1; }
echo "$OUT" | grep -q "test_x" || { echo "FAIL B: failing-test detail not surfaced"; exit 1; }
echo "B ok"

# Case C: --no-verify bypasses the failing gate
git commit -q --no-verify -m init && echo "C ok" || { echo "FAIL C: --no-verify did not bypass"; exit 1; }

# Case D: testCmd passes -> commit succeeds
mk_repo "true"
git commit -q -m init && echo "D ok" || { echo "FAIL D: passing testCmd blocked commit"; exit 1; }

echo "ALL PASS"
