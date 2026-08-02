set -u
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$SKILL/hooks/auto-commit-context.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# --- Case A: a dirty context/ repo gets auto-committed ---
mkdir -p "$TMP/proj/context"
cd "$TMP/proj/context"
echo '<html><head><title>x</title></head></html>' > index.html
echo '{"projectName":"proj"}' > config.json
git init -q . && git add -A && git commit -q -m init
echo "change" >> index.html   # make it dirty
before=$(git rev-list --count HEAD)
printf '{"hook_event_name":"Stop","cwd":"%s/proj/context"}' "$TMP" | FIRSTMATE_HOME="$TMP/nofm" bash "$HOOK"
after=$(git rev-list --count HEAD)
[ "$after" -eq "$((before+1))" ] || { echo "FAIL: dirty context not committed ($before->$after)"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "FAIL: context still dirty after hook"; exit 1; }

# --- Case B: a NON-context repo (parent code repo) is NEVER committed ---
mkdir -p "$TMP/code"
cd "$TMP/code"
echo 'print(1)' > app.py
git init -q . && git add -A && git commit -q -m init
echo 'print(2)' >> app.py   # dirty code repo
cbefore=$(git rev-list --count HEAD)
# cwd is the code repo (no context/ inside); FIRSTMATE_HOME points nowhere
printf '{"hook_event_name":"Stop","cwd":"%s/code"}' "$TMP" | FIRSTMATE_HOME="$TMP/nofm" bash "$HOOK"
cafter=$(git rev-list --count HEAD)
[ "$cafter" -eq "$cbefore" ] || { echo "FAIL: code repo was committed! ($cbefore->$cafter)"; exit 1; }
[ -n "$(git status --porcelain)" ] || { echo "FAIL: code repo got cleaned (should be untouched)"; exit 1; }

# --- Case C: flag autoCommitContext=false disables it ---
mkdir -p "$TMP/proj2/context"
cd "$TMP/proj2/context"
echo '<html><head><title>y</title></head></html>' > index.html
echo '{"projectName":"proj2","autoCommitContext":false}' > config.json
git init -q . && git add -A && git commit -q -m init
echo "change" >> index.html
fbefore=$(git rev-list --count HEAD)
printf '{"hook_event_name":"Stop","cwd":"%s/proj2/context"}' "$TMP" | FIRSTMATE_HOME="$TMP/nofm" bash "$HOOK"
fafter=$(git rev-list --count HEAD)
[ "$fafter" -eq "$fbefore" ] || { echo "FAIL: flag=false did not disable commit"; exit 1; }

# --- Case D: clean context repo → no empty commit ---
cd "$TMP/proj/context"
gbefore=$(git rev-list --count HEAD)
printf '{"hook_event_name":"Stop","cwd":"%s/proj/context"}' "$TMP" | FIRSTMATE_HOME="$TMP/nofm" bash "$HOOK"
gafter=$(git rev-list --count HEAD)
[ "$gafter" -eq "$gbefore" ] || { echo "FAIL: clean repo got an empty commit"; exit 1; }

echo "PASS"

# --- Case E: firstmate-home layout (repo root = home, context/ is a subdir) ---
mkdir -p "$TMP/fmhome/context"
cd "$TMP/fmhome"
echo '<html><head><title>fm</title></head></html>' > context/index.html
echo '{"projectName":"fm","scope":"global"}' > context/config.json
git init -q . && git add -A && git commit -q -m init
echo "change" >> context/index.html
ebefore=$(git rev-list --count HEAD)
# cwd is the home; FIRSTMATE_HOME points at it → its context/ should commit (via root repo)
printf '{"hook_event_name":"Stop","cwd":"%s/fmhome"}' "$TMP" | FIRSTMATE_HOME="$TMP/fmhome" bash "$HOOK"
eafter=$(git rev-list --count HEAD)
[ "$eafter" -eq "$((ebefore+1))" ] || { echo "FAIL: firstmate-home layout not committed ($ebefore->$eafter)"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "FAIL: fmhome still dirty"; exit 1; }

# --- Case F: code repo with a context/ subdir is NOT committed wholesale ---
# (guard must refuse when toplevel != ctx dir AND != trusted firstmate home)
mkdir -p "$TMP/realcode/context"
cd "$TMP/realcode"
echo 'print(1)' > app.py
echo '<html><head><title>c</title></head></html>' > context/index.html
echo '{"projectName":"realcode"}' > context/config.json
git init -q . && git add -A && git commit -q -m init   # ONE repo at root, context is subdir, NOT firstmate
echo 'print(2)' >> app.py        # dirty CODE
echo 'x' >> context/index.html   # dirty context
rbefore=$(git rev-list --count HEAD)
# cwd inside, FIRSTMATE_HOME elsewhere → guard should REFUSE (toplevel=realcode, not a context dir, not fm home)
printf '{"hook_event_name":"Stop","cwd":"%s/realcode/context"}' "$TMP" | FIRSTMATE_HOME="$TMP/none" bash "$HOOK"
rafter=$(git rev-list --count HEAD)
[ "$rafter" -eq "$rbefore" ] || { echo "FAIL: code-repo-with-context-subdir got committed! ($rbefore->$rafter)"; exit 1; }
grep -q 'print(2)' app.py && [ -n "$(git status --porcelain app.py)" ] || { echo "FAIL: app.py change lost"; exit 1; }

echo "PASS-EXTENDED"
