#!/usr/bin/env bash
# capture-on-stop.sh — Stop hook. Advisory (always exit 0). End-of-session capture
# sweep: surfaces a one-line reminder telling the agent to deposit any durable
# decisions/failures/open-questions into capture-inbox.html via capture-candidates.py.
# It does NOT itself parse the transcript — the LLM owns classification; this hook
# guarantees the prompt to do so fires every session. Writes to stderr, exit 0.
set -u
cat >/dev/null 2>&1

HOME_DIR="${FIRSTMATE_HOME:-$HOME/.claude/firstmate}"
CTX="$HOME_DIR/context"
INBOX="$CTX/capture-inbox.html"
[ -f "$INBOX" ] || exit 0

echo "[capture] Session ending. If any durable decision/failure/open-question surfaced," >&2
echo "[capture] deposit it (no live-graph writes):" >&2
echo "[capture]   python3 $CTX/scripts/capture-candidates.py --inbox $INBOX \\" >&2
echo "[capture]     --kind decision|failure|open-question --summary \"<one line>\" --source \$CLAUDE_SESSION_ID" >&2
exit 0
