#!/usr/bin/env bash
# UserPromptSubmit hook: reminds the agent to read context/index.html before
# responding to ANY task — not just edits. Fires on every user message until
# the sentinel is created by post-read-context-gate.sh.

SENTINEL="/tmp/.claude_context_read_${CLAUDE_SESSION_ID:-default}"

if [[ ! -f "$SENTINEL" ]]; then
  echo "REMINDER: You have NOT read context/index.html yet this session."
  echo "You MUST read context/index.html BEFORE responding to ANY task — questions, edits, scope checks, anything."
  echo "Do it NOW. No exceptions. No rationalizing."
  exit 0
fi

exit 0
