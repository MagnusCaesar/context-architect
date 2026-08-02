#!/usr/bin/env bash
# Combined PreToolUse hook: source guard + auto-lock + heartbeat + context injection.
# Replaces: pre-edit-lock-check-wrapper.sh, pre-edit-source-guard.sh
#
# Exit 0 = allow (stderr shown to agent as context)
# Exit 2 = block (stdout shown to agent as error)

INPUT=$(cat)
FILE=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)
AID=$(echo "$INPUT" | python3 -c "import json,sys;print(json.load(sys.stdin).get('agent_id',''))" 2>/dev/null)

[[ -z "$FILE" ]] && exit 0

# --- Source guard: block edits to read-only directories ---
if [[ "$FILE" == *"input_rpts/"* ]] || [[ "$FILE" == *"/processed/"* ]] || [[ "$FILE" == *"/logs/"* ]]; then
    echo "BLOCKED: read-only directory."
    exit 2
fi

# --- Locate context root (walk upward from file) ---
CONTEXT_DIR=""
CHECK="$FILE"
while [[ "$CHECK" != "/" ]]; do
    CHECK=$(dirname "$CHECK")
    if [[ -f "$CHECK/context/index.html" ]]; then
        CONTEXT_DIR="$CHECK/context"
        break
    fi
    if [[ -f "$CHECK/index.html" ]] && [[ -f "$CHECK/config.json" ]]; then
        CONTEXT_DIR="$CHECK"
        break
    fi
done

[[ -z "$CONTEXT_DIR" ]] && exit 0
[[ ! -f "$CONTEXT_DIR/index.html" ]] && exit 0

SCRIPTS_DIR="$CONTEXT_DIR/scripts"
AGENT="${AID:-${AGENT_ID:-orchestrator}}"

# Config: auto-acquire lock on edit? (default true if unset)
AUTO_ACQUIRE=$(python3 -c "
import sys; sys.path.insert(0, '$SCRIPTS_DIR')
from pathlib import Path
from context_utils import read_config
cfg = read_config(Path('$CONTEXT_DIR'))
print('false' if cfg.get('autoAcquireOnEdit') is False else 'true')
" 2>/dev/null || echo true)

# Touch heartbeat on every edit (invisible to agent, feeds contention-aware fast break)
python3 -c "
import sys; sys.path.insert(0, '$SCRIPTS_DIR')
from context_utils import find_context_root, touch_heartbeat
root = find_context_root()
if root:
    touch_heartbeat(root, '$AGENT')
" 2>/dev/null || true

# --- Context page edit: auto-lock + inject ---
if [[ "$FILE" == *"context/"* ]] && [[ "$FILE" == *".html" ]]; then
    BASENAME=$(basename "$FILE")

    # Skip index.html (no locking needed)
    [[ "$BASENAME" == "index.html" ]] && exit 0

    # Page path relative to context root (e.g. decisions/dec-002.html) — needed so
    # start-task.py can resolve pages that live in subdirectories, not just top-level.
    PAGE_REL=$(python3 -c "
import sys
from pathlib import Path
try:
    print(Path('$FILE').resolve().relative_to(Path('$CONTEXT_DIR').resolve()).as_posix())
except ValueError:
    print('$BASENAME')
" 2>/dev/null)
    [[ -z "$PAGE_REL" ]] && PAGE_REL="$BASENAME"

    # Check current lock state
    read_meta() {
        python3 - "$1" "$2" <<'PY'
import re, sys
path, name = sys.argv[1], sys.argv[2]
text = open(path, errors="replace").read()
m = re.search(r'<meta\s+name="' + re.escape(name) + r'"\s+content="([^"]*)"', text)
print(m.group(1) if m else "")
PY
    }

    # New file creation (doesn't exist yet) — nothing to lock/contend on, allow
    [[ ! -f "$FILE" ]] && exit 0

    LOCKED=$(read_meta "$FILE" "locked")
    LOCKED_BY=$(read_meta "$FILE" "locked-by")

    if [[ "$LOCKED" == "true" ]] && { [[ "$LOCKED_BY" == "$AGENT" ]] || [[ "$LOCKED_BY" == "orchestrator" ]] || [[ -z "$LOCKED_BY" ]]; }; then
        # Owned by us or orchestrator — proceed without re-acquiring
        :
    elif [[ "$AUTO_ACQUIRE" != "true" ]]; then
        # autoAcquireOnEdit disabled: old behavior — require a held lock, else block
        if [[ "$LOCKED" != "true" ]]; then
            echo "BLOCKED: Page $BASENAME is not locked. Run start-task.py first."
            exit 2
        fi
        echo "BLOCKED: Page $BASENAME locked by $LOCKED_BY, not $AGENT. Run start-task.py first."
        exit 2
    else
        # Either unlocked (needs acquire) or locked by someone else (contention path)
        RESULT=$(python3 "$SCRIPTS_DIR/start-task.py" --page "$PAGE_REL" --agent-id "$AGENT" --intent "auto-acquire on edit" --lines 5 --files 1 2>/dev/null)
        STATUS=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)

        if [[ "$STATUS" == "acquired" ]] || [[ "$STATUS" == "broke_stale_lock" ]]; then
            echo "[auto-lock] Acquired lock on $BASENAME" >&2
        elif [[ "$STATUS" == "blocked_lock_busy" ]]; then
            echo "BLOCKED: lock mutex busy (>10s), retry"
            exit 2
        elif [[ "$STATUS" == "blocked_active_lock" ]]; then
            REASON=$(echo "$RESULT" | python3 -c "import json,sys; r=json.load(sys.stdin); print(r.get('lock_status',{}).get('reason', r.get('reason','unknown')))" 2>/dev/null)
            echo "BLOCKED: Cannot acquire lock on $BASENAME: $REASON"
            exit 2
        else
            echo "BLOCKED: Lock acquisition failed on $BASENAME (status=$STATUS)"
            exit 2
        fi
    fi

    # Inject context for this page
    INJECT=$(python3 "$SCRIPTS_DIR/find-tracking-page.py" "$FILE" 2>/dev/null)
    if [[ -n "$INJECT" ]]; then
        echo "--- Context for $BASENAME ---" >&2
        echo "$INJECT" >&2
        echo "---" >&2
    fi

    exit 0
fi

# --- Source file edit: inject relevant context ---
INJECT=$(python3 "$SCRIPTS_DIR/find-tracking-page.py" "$FILE" 2>/dev/null)
if [[ -n "$INJECT" ]]; then
    echo "--- Context for $(basename "$FILE") ---" >&2
    echo "$INJECT" >&2
    echo "---" >&2
fi

# Opportunistic stale-lock reap + surface pending contentions (non-blocking)
python3 -c "
import sys; sys.path.insert(0, '$SCRIPTS_DIR')
from context_utils import find_context_root, reap_stale_locks, read_pending_contentions
root = find_context_root()
if root:
    reaped = reap_stale_locks(root)
    for r in reaped:
        print(f\"[auto-release] Reaped: {r['page']} (owner={r['agent']}, reason={r['reason']})\", file=sys.stderr)
    pending = read_pending_contentions(root)
    if pending:
        print('[contention] Pending resolution:', file=sys.stderr)
        for p in pending:
            print(f\"  {p['agent']} wants {p['page']}: {p.get('intent','?')}\", file=sys.stderr)
" 2>&2 || true

exit 0
