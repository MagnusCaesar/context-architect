#!/usr/bin/env bash
# subagent-start-inject.sh — SubagentStart hook. Injects context into a spawned
# subagent via hookSpecificOutput.additionalContext.
# Project-aware: tree-walks from the subagent's cwd for a project context/, else
# falls back to the global first-mate registry. Advisory: always exit 0.
#
# [subagent-hook-inheritance]: SubagentStart DOES fire for Task subagents on Claude
# Code 2.1.203 (verified 2026-07-07 by raw-payload probe; payload carries agent_id).
# This reverses the 2.1.201 finding — this injection is LIVE, not dead code. Project
# CLAUDE.md remains a parallel inherited channel; the orchestrate spawn-prompt slice
# still carries AGENT_ID belt-and-suspenders. On CC <2.1.201 this hook is a no-op.
set -u
INPUT="$(cat)"
CWD="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('cwd',''))
except Exception:
    print('')
" 2>/dev/null)"
[ -n "$CWD" ] || CWD="$PWD"

# 1) Tree-walk upward from CWD for a project context root (mirrors pre-edit hook).
CONTEXT_DIR=""
CHECK="$CWD"
while [ "$CHECK" != "/" ] && [ -n "$CHECK" ]; do
    if [ -f "$CHECK/context/index.html" ]; then CONTEXT_DIR="$CHECK/context"; break; fi
    if [ -f "$CHECK/index.html" ] && [ -f "$CHECK/config.json" ]; then CONTEXT_DIR="$CHECK"; break; fi
    CHECK="$(dirname "$CHECK")"
done

emit() {  # $1 = the additionalContext text
    python3 - "$1" <<'PY'
import json,sys
print(json.dumps({"hookSpecificOutput":{"hookEventName":"SubagentStart","additionalContext":sys.argv[1]}}))
PY
}

counts_line() {  # $1 = context dir; echoes "Open: D decisions, Q open questions — see ..."
    local d="$1/decisions" oq="$1/open-questions" f status dc=0 qc=0
    if [ -d "$d" ]; then
        for f in "$d"/dec-*.html; do
            [ -f "$f" ] || continue
            status=$(grep -o '<meta name="status" content="[^"]*"' "$f" 2>/dev/null | sed 's/.*content="//;s/"$//')
            case "$status" in superseded|deprecated|rejected) continue;; esac
            dc=$((dc + 1))
        done
    fi
    if [ -d "$oq" ]; then
        for f in "$oq"/oq-*.html "$oq"/[0-9]*.html; do
            [ -f "$f" ] || continue
            case "$(basename "$f")" in archive.html|index.html) continue;; esac
            qc=$((qc + 1))
        done
        # also catch any *.html not named archive/index if oq-*.html matched nothing
        if [ "$qc" -eq 0 ]; then
            for f in "$oq"/*.html; do
                [ -f "$f" ] || continue
                case "$(basename "$f")" in archive.html|index.html) continue;; esac
                qc=$((qc + 1))
            done
        fi
    fi
    printf 'Open: %d decisions, %d open questions — see %s/decisions.html and open-questions.html. Specific decisions + ancestry are injected when you edit a relevant file.' "$dc" "$qc" "$1"
}

if [ -n "$CONTEXT_DIR" ]; then
    TEXT="PROJECT CONTEXT (you are a subagent working in this project).
Entry point: $CONTEXT_DIR/index.html — read it before acting.
$(counts_line "$CONTEXT_DIR")"
    emit "$TEXT"
    exit 0
fi

# 2) Fallback: global first-mate registry.
HOME_DIR="${FIRSTMATE_HOME:-$HOME/.claude/firstmate}"
GCTX="$HOME_DIR/context"
if [ -f "$GCTX/index.html" ]; then
    REG="$GCTX/project-registry.html"
    REGTXT=""
    if [ -f "$REG" ]; then
        REGTXT="$(awk '
        /<article/ {l=$0;gsub(/<[^>]*>/,"",l);gsub(/^[[:space:]]+|[[:space:]]+$/,"",l);if(l!="")print l;a=1;next}
        /<\/article>/{a=0;next}
        a {l=$0;gsub(/<[^>]*>/,"",l);gsub(/^[[:space:]]+|[[:space:]]+$/,"",l);if(l!="")print l}' "$REG" 2>/dev/null)"
    fi
    emit "FIRST-MATE (global context). Entry point: $GCTX/index.html. Projects:
$REGTXT"
    exit 0
fi

exit 0  # nothing to inject
