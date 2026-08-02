#!/usr/bin/env bash
# Combined PostToolUse hook: validation warning + line count + staleness.
# Replaces: post-edit-validate-wrapper.sh, post-edit-staleness-check.sh
# Always exits 0 (non-blocking, advisory only).

INPUT=$(cat)
FILE=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

[[ -z "$FILE" ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

# --- Locate context root ---
CONTEXT_DIR=""
CHECK="$FILE"
while [[ "$CHECK" != "/" ]]; do
    CHECK=$(dirname "$CHECK")
    if [[ -f "$CHECK/context/index.html" ]]; then
        CONTEXT_DIR="$CHECK/context"
        PROJECT_ROOT="$CHECK"
        break
    fi
    if [[ -f "$CHECK/index.html" ]] && [[ -f "$CHECK/config.json" ]]; then
        CONTEXT_DIR="$CHECK"
        PROJECT_ROOT=$(dirname "$CHECK")
        break
    fi
done

[[ -z "$CONTEXT_DIR" ]] && exit 0

# --- Context page edits: line count + validation ---
if [[ "$FILE" == *"context/"* ]] && [[ "$FILE" == *".html" ]]; then
    BASENAME=$(basename "$FILE")

    # Line count warning (ledger.html exempt)
    if [[ "$BASENAME" != "ledger.html" ]]; then
        LINE_COUNT=$(wc -l < "$FILE")
        if [[ $LINE_COUNT -gt 150 ]]; then
            echo "WARNING: $BASENAME is $LINE_COUNT lines (soft limit: 150, hard limit: 200). Consider splitting." >&2
        fi
    fi

    # Run validation (non-blocking)
    VALIDATE_OUTPUT=$(cd "$PROJECT_ROOT" && python3 "$CONTEXT_DIR/scripts/validate.py" 2>/dev/null)
    VALIDATE_EXIT=$?

    if [[ $VALIDATE_EXIT -ne 0 ]]; then
        FAILURES=$(echo "$VALIDATE_OUTPUT" | grep -A1 "^FAIL:" | head -6)
        if [[ -n "$FAILURES" ]]; then
            echo "--- Validation issues ---" >&2
            echo "$FAILURES" >&2
            echo "---" >&2
        fi
    fi

    exit 0
fi

# --- Source file edits: staleness check for impl pages ---
REL_PATH=$(python3 -c "
import sys
from pathlib import Path
try:
    rel = str(Path('$FILE').resolve().relative_to(Path('$PROJECT_ROOT').resolve()))
    print(rel)
except ValueError:
    pass
" 2>/dev/null)

[[ -z "$REL_PATH" ]] && exit 0

STALE_PAGES=""
if [[ -d "$CONTEXT_DIR/impl" ]]; then
    for page in "$CONTEXT_DIR"/impl/*.html; do
        [[ ! -f "$page" ]] && continue
        if grep -q "$REL_PATH" "$page" 2>/dev/null; then
            STALE_PAGES="$STALE_PAGES $(basename "$page")"
        fi
    done
fi

if [[ -n "$STALE_PAGES" ]]; then
    echo "STALE: impl page(s) track this file:$STALE_PAGES -- update after your edits." >&2
fi

exit 0
