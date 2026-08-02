#!/usr/bin/env bash
# Proves Change C: pre-edit-context-inject.sh reads agent_id from the PreToolUse
# JSON payload and uses it as the lock owner. With agent_id present -> owner is
# that agent; absent -> owner falls back to orchestrator.
#
# Run: bash test_agent_id_from_payload.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$(dirname "$HERE")"
HOOK="$SKILL/hooks/pre-edit-context-inject.sh"
REAL_SCRIPTS="$SKILL/scripts"

fail() { echo "FAIL: $1"; exit 1; }

# Build a fresh temp context tree with an unlocked page.
make_ctx() {
    TMP="$(mktemp -d)"
    mkdir -p "$TMP/context"
    echo '<html><head></head><body></body></html>' > "$TMP/context/index.html"
    printf '{"defaultRole":"orchestrator","lockMutexTimeoutSec":10}' > "$TMP/context/config.json"
    ln -s "$REAL_SCRIPTS" "$TMP/context/scripts"
    printf '<html><head><meta name="locked" content="false"><meta name="locked-by" content=""></head><body></body></html>' \
        > "$TMP/context/foo.html"
}

owner_of() {
    python3 -c "
import re,sys
t=open('$1').read()
m=re.search(r'<meta name=\"locked-by\" content=\"([^\"]*)\"',t)
print(m.group(1) if m else '')"
}

# Case 1: agent_id present in payload -> owner == worker-XYZ
make_ctx
PAYLOAD1=$(python3 -c "import json;print(json.dumps({'tool_input':{'file_path':'$TMP/context/foo.html'},'agent_id':'worker-XYZ'}))")
( cd "$TMP" && printf '%s' "$PAYLOAD1" | env -u AGENT_ID bash "$HOOK" >/dev/null 2>&1 )
OWNER1=$(owner_of "$TMP/context/foo.html")
[ "$OWNER1" = "worker-XYZ" ] || fail "with agent_id: expected owner worker-XYZ, got '$OWNER1'"
echo "PASS: agent_id in payload -> lock owner = worker-XYZ"
rm -rf "$TMP"

# Case 2: no agent_id in payload, AGENT_ID unset -> owner == orchestrator
make_ctx
PAYLOAD2=$(python3 -c "import json;print(json.dumps({'tool_input':{'file_path':'$TMP/context/foo.html'}}))")
( cd "$TMP" && printf '%s' "$PAYLOAD2" | env -u AGENT_ID bash "$HOOK" >/dev/null 2>&1 )
OWNER2=$(owner_of "$TMP/context/foo.html")
[ "$OWNER2" = "orchestrator" ] || fail "no agent_id: expected owner orchestrator, got '$OWNER2'"
echo "PASS: no agent_id in payload -> lock owner = orchestrator"
rm -rf "$TMP"

echo "ALL PASS"
