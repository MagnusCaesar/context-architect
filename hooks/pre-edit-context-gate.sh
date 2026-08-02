#!/usr/bin/env bash
# PreToolUse hook: blocks Edit/Write on a project file unless the tracking page
# for THAT SPECIFIC FILE was read in the current session.
#
# Mechanism: PostToolUse partner (post-read-context-gate.sh) writes a per-page
# sentinel when a context page is read. find-tracking-page.py resolves the
# file -> tracking page(s); this hook checks the matching per-page sentinel.
#
# No tracking page for the file  -> allow (no new friction on untracked files).
# Exemptions: memory files, .claude/ config, context/ pages themselves.
#
# Exit 0 = allow. Exit 2 = block (message on stdout names the page(s) to read).

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only enforce for Edit and Write
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty')

# Exempt: memory, .claude config, context/ pages (handled by lock/inject hooks)
if [[ "$FILE_PATH" == *"/memory/"* || "$FILE_PATH" == *"/.claude/"* || "$FILE_PATH" == *"MEMORY.md"* ]]; then
  exit 0
fi
if [[ "$FILE_PATH" == *"context/"* && "$FILE_PATH" == *".html" ]]; then
  exit 0
fi

# Walk up from the file to find a project root containing context/index.html
DIR=$(dirname "$FILE_PATH")
PROJECT_ROOT=""
while [[ "$DIR" != "/" ]]; do
  if [[ -f "$DIR/context/index.html" ]]; then
    PROJECT_ROOT="$DIR"
    break
  fi
  DIR=$(dirname "$DIR")
done

# No context architecture found -> don't block
if [[ -z "$PROJECT_ROOT" ]]; then
  exit 0
fi

SCRIPTS_DIR="$PROJECT_ROOT/context/scripts"

# Resolve file -> tracking page(s). Parse the "=== TRACKING PAGES ===" section
# of find-tracking-page.py output (paths relative to context root).
PAGES=$(cd "$PROJECT_ROOT" 2>/dev/null && python3 "$SCRIPTS_DIR/find-tracking-page.py" "$FILE_PATH" 2>/dev/null \
  | awk '/^=== TRACKING PAGES ===/{f=1;next} /^===/{f=0} f{print $1}')

# No tracking page for this file -> allow (clean fallback, no new friction)
if [[ -z "$PAGES" ]]; then
  exit 0
fi

# Block unless every tracking page has a per-page sentinel for this session.
# Sentinel key must match post-read-context-gate.sh: context-relative path,
# with '/' -> '_'.
SESSION="${CLAUDE_SESSION_ID:-default}"
MISSING=""
while IFS= read -r page; do
  [[ -z "$page" ]] && continue
  key=$(echo "$page" | tr '/' '_')
  SENTINEL="/tmp/.claude_context_page_${SESSION}_${key}"
  if [[ ! -f "$SENTINEL" ]]; then
    MISSING="${MISSING:+$MISSING }$page"
  fi
done <<< "$PAGES"

if [[ -n "$MISSING" ]]; then
  echo "BLOCKED: read the tracking page(s) for this file first: $MISSING (under $PROJECT_ROOT/context/)"
  exit 2
fi

exit 0
