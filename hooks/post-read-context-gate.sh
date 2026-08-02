#!/usr/bin/env bash
# PostToolUse hook: marks that a context page was read in this session.
# Partner of pre-edit-context-gate.sh.
#
# Writes a per-page sentinel keyed by session + context-relative path (so the
# gate can check whether THIS file's tracking page specifically was read).
# Also keeps the legacy session-wide sentinel for index.html.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only trigger on Read
if [[ "$TOOL_NAME" != "Read" ]]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty')

# Only track reads of context pages
if [[ "$FILE_PATH" != *"context/"* || "$FILE_PATH" != *".html" ]]; then
  exit 0
fi

SESSION="${CLAUDE_SESSION_ID:-default}"

# Legacy session-wide sentinel (index.html read = context entered)
if [[ "$FILE_PATH" == *"context/index.html"* ]]; then
  touch "/tmp/.claude_context_read_${SESSION}"
fi

# Per-page sentinel: context-relative path, '/' -> '_' (must match the gate).
REL=$(echo "$FILE_PATH" | sed -E 's#^.*/context/##')
if [[ -n "$REL" && "$REL" != "$FILE_PATH" ]]; then
  key=$(echo "$REL" | tr '/' '_')
  touch "/tmp/.claude_context_page_${SESSION}_${key}"
fi

exit 0
