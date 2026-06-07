#!/usr/bin/env bash
# PostToolUse hook: validate context/ after any edit to context/*.html
# Install in .claude/settings.local.json:
# "hooks": { "PostToolUse": [{ "matcher": "Edit|Write", "command": "bash ~/.claude/skills/context-architecture/hooks/post-edit-validate.sh \"$FILE\"" }] }

FILE="$1"

# Only trigger for context HTML files
if [[ "$FILE" != *"context/"* ]] || [[ "$FILE" != *".html" ]]; then
    exit 0
fi

# Find context root
CONTEXT_DIR=$(dirname "$FILE")
while [[ ! -f "$CONTEXT_DIR/index.html" ]] && [[ "$CONTEXT_DIR" != "/" ]]; do
    CONTEXT_DIR=$(dirname "$CONTEXT_DIR")
done

if [[ ! -f "$CONTEXT_DIR/index.html" ]]; then
    exit 0
fi

PROJECT_ROOT=$(dirname "$CONTEXT_DIR")

# Run validation (non-blocking, just report)
cd "$PROJECT_ROOT"
python3 "$CONTEXT_DIR/scripts/validate.py" 2>/dev/null
VALIDATE_EXIT=$?

# Regenerate docs
python3 "$CONTEXT_DIR/scripts/generate-docs.py" 2>/dev/null

if [[ $VALIDATE_EXIT -ne 0 ]]; then
    echo "⚠ Context validation found issues. Run: python context/scripts/validate.py"
fi
