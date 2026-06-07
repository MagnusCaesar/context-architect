#!/usr/bin/env bash
# End-to-end smoke test for context-architecture skill.
# Exercises: bootstrap → start-task → edit → close-task → validate → freshness → docs
# Exit 0 = all pass, 1 = failure.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$SKILL_DIR/scripts"
TMP=$(mktemp -d)
PASS=0
FAIL=0

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

step() {
    local name="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name"
        FAIL=$((FAIL + 1))
    fi
}

step_output() {
    local name="$1"
    local pattern="$2"
    shift 2
    local out
    out=$("$@" 2>&1) || true
    if echo "$out" | grep -q "$pattern"; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name (expected: $pattern)"
        echo "         got: $(echo "$out" | head -3)"
        FAIL=$((FAIL + 1))
    fi
}

step_json_file() {
    local name="$1"
    local file="$2"
    local expr="$3"
    if python3 - "$file" "$expr" <<'PY' >/dev/null 2>&1; then
import json
import sys
path, expr = sys.argv[1], sys.argv[2]
data = json.load(open(path))
if not eval(expr, {"data": data}):
    raise SystemExit(1)
PY
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name"
        echo "         file: $file expr: $expr"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== context-architecture smoke test ==="
echo "Temp project: $TMP"
echo ""

# --- Create fake project ---
mkdir -p "$TMP/src"
cat > "$TMP/src/main.py" << 'PYEOF'
"""Main entry point for fake project."""
import sys
def main():
    print("Hello from fake project")
    return 0
if __name__ == "__main__":
    sys.exit(main())
PYEOF

cat > "$TMP/src/utils.py" << 'PYEOF'
"""Utility functions."""
def helper():
    return 42
PYEOF

cat > "$TMP/README.md" << 'MDEOF'
# Fake Project
A test project for smoke testing the context-architecture skill.
MDEOF

echo "Phase 1: Bootstrap"

# Scan mode (run from original dir — bootstrap takes --target)
step_output "bootstrap --scan produces JSON" '"root"' \
    python3 "$SCRIPTS/bootstrap.py" --target "$TMP" --scan

# Generate mode
step "bootstrap generates context/" \
    python3 "$SCRIPTS/bootstrap.py" --target "$TMP"

# Switch into temp project (scripts use find_context_root from CWD)
cd "$TMP"

# Verify structure
step "index.html exists" test -f "$TMP/context/index.html"
step "ledger.html exists" test -f "$TMP/context/ledger.html"
step "ledger-events.ndjson exists" test -f "$TMP/context/ledger-events.ndjson"
step "agent-tree.html exists" test -f "$TMP/context/agent-tree.html"
step "decisions.html exists" test -f "$TMP/context/decisions.html"
step "config.json exists" test -f "$TMP/context/config.json"
step "runtime-policy.md exists" test -f "$TMP/context/runtime-policy.md"
step "scripts/ populated" test -f "$TMP/context/scripts/validate.py"
step "harden-ledger helper copied" test -f "$TMP/context/scripts/harden-ledger.sh"
step "check-hardening helper copied" test -f "$TMP/context/scripts/check-hardening.py"

echo ""
echo "Phase 2: Task lifecycle"

# Start task (acquire lock)
step_output "start-task acquires lock" '"acquired": true' \
    python3 "$TMP/context/scripts/start-task.py" --page decisions.html --intent "smoke test" --agent-id smoke-agent

step_output "daily hygiene auto-runs before first ledger event" 'data-event="daily_hygiene"' \
    grep -o 'data-event="daily_hygiene"' "$TMP/context/ledger.html"

step_output "daily hygiene source log appended" '"event":"daily_hygiene"' \
    grep -o '"event":"daily_hygiene"' "$TMP/context/ledger-events.ndjson"

step_output "second writer blocked" '"status": "blocked_active_lock"' \
    python3 "$TMP/context/scripts/start-task.py" --page decisions.html --intent "blocked smoke" --agent-id other-agent

step_output "blocked event logged" 'data-status="blocked_active_lock"' \
    grep -o 'data-status="blocked_active_lock"' "$TMP/context/ledger.html"

step_output "daily hygiene runs once per day" '^1$' \
    bash -c "grep -o 'data-event=\"daily_hygiene\"' '$TMP/context/ledger.html' | wc -l | tr -d ' '"

# Verify lock meta changed
step_output "lock meta set to true" 'content="true"' \
    grep -o 'name="locked" content="[^"]*"' "$TMP/context/decisions.html"

# Simulate edit (add a comment inside <main>)
sed -i 's|</main>|    <!-- smoke test was here -->\n  </main>|' "$TMP/context/decisions.html"

# Close task (release lock + validate + regen)
step_output "close-task releases lock" '"released": true' \
    python3 "$TMP/context/scripts/close-task.py" --page decisions.html --summary "smoke test edit" --agent-id smoke-agent --skip-docs

# Verify lock released
step_output "lock meta set to false" 'content="false"' \
    grep -o 'name="locked" content="[^"]*"' "$TMP/context/decisions.html"

# Stale lock break contract.
python3 "$TMP/context/scripts/start-task.py" --page decisions.html --intent "stale setup" --agent-id stale-owner >/dev/null
python3 - <<'PY'
from pathlib import Path
p = Path("context/decisions.html")
s = p.read_text()
s = s.replace('name="locked-at" content="', 'name="locked-at" content="2000-01-01T00:00:00Z')
start = s.find('name="locked-at" content="2000-01-01T00:00:00Z')
if start != -1:
    end = s.find('"', start + len('name="locked-at" content="2000-01-01T00:00:00Z'))
    s = s[:start + len('name="locked-at" content="2000-01-01T00:00:00Z')] + s[end:]
p.write_text(s)
PY
step_output "worker stale lock break blocked" '"action": "orchestrator_resolution_required"' \
    python3 "$TMP/context/scripts/start-task.py" --page decisions.html --intent "break stale" --agent-id stale-breaker
step_output "orchestrator stale lock broken" '"status": "broke_stale_lock"' \
    python3 "$TMP/context/scripts/start-task.py" --page decisions.html --intent "break stale" --agent-id orchestrator
python3 "$TMP/context/scripts/close-task.py" --page decisions.html --summary "stale smoke" --agent-id orchestrator --skip-docs >/dev/null

echo ""
echo "Phase 3: Utilities"

# Validate
step "validate.py passes" \
    python3 "$TMP/context/scripts/validate.py"

step_output "check-hardening reports status" '"status":' \
    python3 "$TMP/context/scripts/check-hardening.py" --json

# Check freshness
step "check-freshness.py runs" \
    python3 "$TMP/context/scripts/check-freshness.py"

python3 "$TMP/context/scripts/check-reachability.py" --json > /tmp/reachability.json
step_json_file "reachability fallback root warning" /tmp/reachability.json "data['fallback_root'] is True and data['root'] == 'context/index.html'"

python3 "$TMP/context/scripts/record-agent.py" --agent-id worker-1 --parent-id orchestrator --role verifier --task "check decisions" --page decisions.html --status spawned --actor-id orchestrator >/tmp/agent-spawn.json
step_json_file "record-agent records spawn" /tmp/agent-spawn.json "data['status'] == 'recorded' and data['ledger_appended'] is True"
step_output "agent tree row rendered" 'data-agent="worker-1"' \
    grep -o 'data-agent="worker-1"' "$TMP/context/agent-tree.html"
step_output "agent lifecycle logged" 'data-event="agent_spawned"' \
    grep -o 'data-event="agent_spawned"' "$TMP/context/ledger.html"
python3 "$TMP/context/scripts/record-agent.py" --agent-id worker-1 --status active --details heartbeat >/tmp/agent-active.json
step_json_file "record-agent active avoids ledger" /tmp/agent-active.json "data['status'] == 'recorded' and data['ledger_appended'] is False"

mkdir -p "$TMP/context/sub"
cat > "$TMP/context/sub/nested.html" <<'HTMLEOF'
<!DOCTYPE html>
<html><head>
  <meta name="title" content="Nested">
  <meta name="created" content="2026-01-01">
  <meta name="updated" content="2026-01-01">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="tracks" content="context-only">
</head><body><main></main></body></html>
HTMLEOF
python3 - <<'PY'
from pathlib import Path
p = Path("context/index.html")
s = p.read_text()
s = s.replace("</ul>", '        <li><a href="./sub/nested.html">nested</a></li>\n      </ul>', 1)
p.write_text(s)
PY
python3 "$TMP/context/scripts/check-reachability.py" --json > /tmp/reachability-nested.json
step_json_file "reachability returns shortest path" /tmp/reachability-nested.json "'context/sub/nested.html' in data['paths'] and data['paths']['context/sub/nested.html'][0] == 'context/index.html'"
python3 - <<'PY'
from pathlib import Path
p = Path("context/index.html")
p.write_text(p.read_text().replace('        <li><a href="./sub/nested.html">nested</a></li>\n', ""))
Path("context/sub/nested.html").unlink()
Path("context/sub").rmdir()
PY

cat > "$TMP/context/orphan.html" <<'HTMLEOF'
<!DOCTYPE html>
<html><head>
  <meta name="title" content="Orphan">
  <meta name="created" content="2026-01-01">
  <meta name="updated" content="2026-01-01">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="tracks" content="context-only">
</head><body><main></main></body></html>
HTMLEOF
python3 "$TMP/context/scripts/check-reachability.py" --json > /tmp/reachability-orphan.json
step_json_file "reachability reports orphan handoff" /tmp/reachability-orphan.json "'context/orphan.html' in data['orphans'] and data['handoff_request']['type'] == 'context_hygiene_request'"
rm -f "$TMP/context/orphan.html"

step_output "worker update-tracks denied" '"status": "permission_denied"' \
    python3 "$TMP/context/scripts/update-tracks.py" --page decisions.html --add src/main.py --agent-id smoke-agent

python3 "$TMP/context/scripts/update-tracks.py" --page decisions.html --add src/main.py --agent-id orchestrator >/tmp/update-tracks.json
step_output "update-tracks logs event" 'data-event="track_update"' \
    grep -o 'data-event="track_update"' "$TMP/context/ledger.html"

step_output "update-tracks source log appended" '"event":"track_update"' \
    grep -o '"event":"track_update"' "$TMP/context/ledger-events.ndjson"

python3 "$TMP/context/scripts/route-diff.py" --files src/main.py > /tmp/route-diff.json
step_json_file "route-diff maps changed file" /tmp/route-diff.json "any(p['page'] == 'decisions.html' for p in data['matched_pages'])"

python3 "$TMP/context/scripts/update-tracks.py" --page decisions.html --add src/missing.py --agent-id orchestrator >/dev/null
python3 "$TMP/context/scripts/route-diff.py" --files src/other.py > /tmp/route-stale.json
step_json_file "route-diff reports stale track" /tmp/route-stale.json "any(item['page'] == 'decisions.html' for item in data['stale_tracks'])"
python3 "$TMP/context/scripts/update-tracks.py" --page decisions.html --remove src/missing.py --agent-id orchestrator >/dev/null

python3 - <<'PY'
from pathlib import Path
p = Path("context/decisions.html")
s = p.read_text()
s = s.replace('data-tracks="context-only"', 'data-tracks="src/main.py"', 1)
p.write_text(s)
PY
python3 "$TMP/context/scripts/route-diff.py" --files src/main.py > /tmp/route-decision.json
step_json_file "route-diff reports affected decision" /tmp/route-decision.json "any(d['decision'] == 'dec-001' for d in data['affected_decisions'])"

cat > "$TMP/context/untracked.html" <<'HTMLEOF'
<!DOCTYPE html>
<html><head>
  <meta name="title" content="Untracked">
  <meta name="created" content="2026-01-01">
  <meta name="updated" content="2026-01-01">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
</head><body><main></main></body></html>
HTMLEOF
python3 "$TMP/context/scripts/check-freshness.py" --page untracked.html --json > /tmp/freshness-untracked.json
step_json_file "freshness reports untracked" /tmp/freshness-untracked.json "data[0]['status'] == 'untracked'"
rm -f "$TMP/context/untracked.html"

python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, "context/scripts")
from context_utils import write_atomic
p = Path("context/atomic-test.txt")
write_atomic(p, "new-content")
assert p.read_text() == "new-content"
assert not list(p.parent.glob(".atomic-test.txt.tmp.*"))
PY
step "atomic helper writes without temp leftovers" test -f "$TMP/context/atomic-test.txt"
rm -f "$TMP/context/atomic-test.txt"

# Generate docs
step "generate-docs.py runs" \
    python3 "$TMP/context/scripts/generate-docs.py"

step "docs/ directory has .md files" \
    test -f "$TMP/context/docs/index.md"

echo ""
echo "Phase 4: Read-only path"

step_output "start-task --read-only" '"task_class": "read-only"' \
    python3 "$TMP/context/scripts/start-task.py" --read-only

echo ""
echo "Phase 5: Validation warning contract"

python3 - <<'PY'
from pathlib import Path
p = Path("context/decisions.html")
s = p.read_text()
s = s.replace("<dt>Review when</dt><dd>HTML pages stop fitting the project workflow or generated markdown becomes the source of truth.</dd>\n", "", 1)
p.write_text(s)
PY
if python3 "$TMP/context/scripts/validate.py" >/tmp/decision-invalid.out 2>&1; then
    echo "  [FAIL] invalid decision fails validation"
    FAIL=$((FAIL + 1))
else
    if grep -q "missing decision field 'Review when'" /tmp/decision-invalid.out; then
        echo "  [PASS] invalid decision fails validation"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] invalid decision fails validation"
        head -5 /tmp/decision-invalid.out
        FAIL=$((FAIL + 1))
    fi
fi
python3 - <<'PY'
from pathlib import Path
p = Path("context/decisions.html")
s = p.read_text()
s = s.replace("<dt>Consequences</dt><dd>Scripts own validation and routing. Agents own judgment about durable meaning.</dd>\n", "<dt>Consequences</dt><dd>Scripts own validation and routing. Agents own judgment about durable meaning.</dd>\n          <dt>Review when</dt><dd>HTML pages stop fitting the project workflow or generated markdown becomes the source of truth.</dd>\n", 1)
p.write_text(s)
PY

python3 "$TMP/context/scripts/start-task.py" --page decisions.html --intent "validation warning" --agent-id warn-agent >/dev/null
python3 - <<'PY'
from pathlib import Path
p = Path("context/decisions.html")
s = p.read_text()
s = s.replace("</main>", '<a href="./missing.html">missing</a>\n  </main>', 1)
p.write_text(s)
PY
python3 "$TMP/context/scripts/close-task.py" --page decisions.html --summary "broken link smoke" --agent-id warn-agent --skip-docs > /tmp/close-warning.json
step_json_file "close-task validation warning status" /tmp/close-warning.json "data['status'] == 'validation_warning'"
step_output "close-task surfaces exact validation failure" 'FAIL: links' \
    grep -o 'FAIL: links' /tmp/close-warning.json
python3 - <<'PY'
from pathlib import Path
p = Path("context/decisions.html")
p.write_text(p.read_text().replace('<a href="./missing.html">missing</a>\n  ', ""))
PY
step "validate.py passes after cleanup" \
    python3 "$TMP/context/scripts/validate.py"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
echo "ALL PASS"
exit 0
