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

# Check if page is locked
LOCKED=$(grep -oP '<meta\s+name="locked"\s+content="\K[^"]+' "$FILE" 2>/dev/null)

if [[ "$LOCKED" == "false" ]] || [[ -z "$LOCKED" ]]; then
    echo "BLOCKED: Page $BASENAME is not locked. Run start-task.py first."
    exit 1
fi

# If we have AGENT_ID, verify ownership
if [[ -n "$AGENT_ID" ]]; then
    LOCKED_BY=$(grep -oP '<meta\s+name="locked-by"\s+content="\K[^"]+' "$FILE" 2>/dev/null)
    if [[ "$LOCKED_BY" != "$AGENT_ID" ]] && [[ "$LOCKED_BY" != "orchestrator" ]]; then
        echo "BLOCKED: Page $BASENAME locked by $LOCKED_BY, not $AGENT_ID."
        exit 1
    fi
fi

exit 0
