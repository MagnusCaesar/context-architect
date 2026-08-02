#!/usr/bin/env bash
# UserPromptSubmit hook: detects decision/failure/question language in the user's
# message and nudges the agent to capture it in the context graph.
#
# Judgment stays with the LLM — this only surfaces a reminder. It never writes
# anything. Fires when the prompt matches capture-trigger phrases.
#
# Exit 0; stdout is injected as context the agent sees.

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('prompt',''))" 2>/dev/null)

[[ -z "$PROMPT" ]] && exit 0

# Lowercase for matching
LOWER=$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]')

NUDGE=""

# Decision language
if echo "$LOWER" | grep -qE "we decided|let'?s (go with|do|use)|decision is|i'?ve decided|confirmed|we'?ll (use|go|do)|settled on|final answer|let'?s commit to"; then
    NUDGE="DECISION"
fi

# Failure language
if echo "$LOWER" | grep -qE "this (is broken|failed|doesn'?t work|crashes)|it broke|regression|that bug|keeps failing"; then
    NUDGE="${NUDGE:+$NUDGE+}FAILURE"
fi

# Open-question language
if echo "$LOWER" | grep -qE "not sure (yet|if|whether|how)|open question|we don'?t know|tbd|need to figure out|still unclear|to be decided"; then
    NUDGE="${NUDGE:+$NUDGE+}QUESTION"
fi

[[ -z "$NUDGE" ]] && exit 0

case "$NUDGE" in
    *DECISION*) echo "[nudge] Possible DECISION → record in context/decisions/ if durable." ;;
esac
case "$NUDGE" in
    *FAILURE*) echo "[nudge] Possible FAILURE → context/failure-todos/ if real+unresolved." ;;
esac
case "$NUDGE" in
    *QUESTION*) echo "[nudge] Possible OPEN QUESTION → context/open-questions/ if blocking." ;;
esac

exit 0
