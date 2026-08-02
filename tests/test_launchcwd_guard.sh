#!/usr/bin/env bash
# test_launchcwd_guard.sh — exercises the launch-cwd enforcement guard in
# session-start-inject.sh. stdlib only, builds temp trees, cleans up.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/hooks/session-start-inject.sh"
[ -f "$HOOK" ] || { echo "FAIL: hook not found at $HOOK"; exit 1; }

MARKER="ENFORCEMENT MAY BE OFF"
fails=0

# realistic settings.json with a PreToolUse matcher (enforcing project)
enforce_settings() {
cat >"$1" <<'JSON'
{ "hooks": { "PreToolUse": [
  { "matcher": "Edit|Write|Bash",
    "hooks": [ { "type": "command", "command": "context/hooks/pretooluse-lock.sh" } ] }
] } }
JSON
}
# settings.json with no hooks (parent that does NOT enforce)
plain_settings() { printf '{ "permissions": { "allow": [] } }\n' >"$1"; }

# run hook with fake SessionStart payload; FIRSTMATE_HOME nulled so it exits
# right after the guard (hermetic, no dependence on real first-mate instance).
run_hook() { FIRSTMATE_HOME="/nonexistent-$$" bash "$HOOK" <<<"{\"cwd\":\"$1\"}"; }

assert_has() {  # $1=label $2=output
    if printf '%s' "$2" | grep -q "$MARKER"; then echo "PASS: $1 (warning fired)"
    else echo "FAIL: $1 (expected warning, none)"; fails=$((fails+1)); fi
}
assert_hasnt() {  # $1=label $2=output
    if printf '%s' "$2" | grep -q "$MARKER"; then echo "FAIL: $1 (unexpected warning)"; fails=$((fails+1))
    else echo "PASS: $1 (no warning)"; fi
}

# --- Case 1 & 2: parent/ + parent/proj (enforcing project) ------------------
T=$(mktemp -d)
mkdir -p "$T/parent/proj/context" "$T/parent/.claude" "$T/parent/proj/.claude"
touch "$T/parent/proj/context/index.html"
plain_settings   "$T/parent/.claude/settings.json"        # parent: no hooks
enforce_settings "$T/parent/proj/.claude/settings.json"   # project: PreToolUse

out1=$(run_hook "$T/parent")        # launched in PARENT then /cd -> bug
assert_has  "case1 /cd-in bug" "$out1"

out2=$(run_hook "$T/parent/proj")   # launched INSIDE project -> ok
assert_hasnt "case2 launched in project" "$out2"

# --- Case 3: no context root anywhere -> no warn, exit 0 --------------------
E=$(mktemp -d); mkdir -p "$E/random/sub"
out3=$(run_hook "$E/random/sub"); rc3=$?
assert_hasnt "case3 no context root" "$out3"
if [ "$rc3" -eq 0 ]; then echo "PASS: case3 exit 0"; else echo "FAIL: case3 exit $rc3"; fails=$((fails+1)); fi

rm -rf "$T" "$E"
echo "---"
[ "$fails" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$fails FAILURE(S)"; exit 1; }
