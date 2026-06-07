#!/usr/bin/env bash
# PreToolUse hook: verify agent holds lock before editing context/*.html
# Install in .claude/settings.local.json:
# "hooks": { "PreToolUse": [{ "matcher": "Edit|Write", "command": "bash ~/.claude/skills/context-architecture/hooks/pre-edit-lock-check.sh \"$FILE\"" }] }

FILE="$1"

# Only trigger for context HTML files (not index.html which is append-only)
if [[ "$FILE" != *"context/"* ]] || [[ "$FILE" != *".html" ]]; then
    exit 0
fi

BASENAME=$(basename "$FILE")
if [[ "$BASENAME" == "index.html" ]]; then
    exit 0
fi

read_meta() {
    python3 - "$FILE" "$1" <<'PY'
import re
import sys
path, name = sys.argv[1], sys.argv[2]
text = open(path, errors="replace").read()
m = re.search(r'<meta\s+name="' + re.escape(name) + r'"\s+content="([^"]*)"', text)
print(m.group(1) if m else "")
PY
}

# Check if page is locked
LOCKED=$(read_meta locked)

if [[ "$LOCKED" != "true" ]]; then
    echo "BLOCKED: Page $BASENAME is not locked. Run start-task.py first."
    exit 1
fi

# If we have AGENT_ID, verify ownership
if [[ -n "$AGENT_ID" ]]; then
    LOCKED_BY=$(read_meta locked-by)
    if [[ "$LOCKED_BY" != "$AGENT_ID" ]] && [[ "$LOCKED_BY" != "orchestrator" ]]; then
        echo "BLOCKED: Page $BASENAME locked by $LOCKED_BY, not $AGENT_ID."
        exit 1
    fi
fi

exit 0
