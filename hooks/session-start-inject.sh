#!/usr/bin/env bash
# session-start-inject.sh — SessionStart hook for the GLOBAL first-mate instance.
# Injects the thin project registry + open global execution decisions into every
# session via stdout (SessionStart stdout is added to session context). Advisory:
# always exits 0. No-op if the instance is absent.
set -u
payload=$(cat 2>/dev/null)  # SessionStart JSON; we need the launch cwd from it
cwd=$(printf '%s' "$payload" | grep -o '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//')

# --- launch-cwd enforcement guard -------------------------------------------
# CC resolves project hooks from the LAUNCH cwd. Launch in a parent dir then
# /cd into a project => project PreToolUse/lock/validate hooks never load and
# nothing says so. Detect that here and self-report. Advisory only.
_dir_up_with() {  # $1=start dir, $2=relative marker -> echo nearest dir (inclusive) up that has it
    local d="$1"
    while :; do
        [ -e "$d/$2" ] && { printf '%s\n' "$d"; return 0; }
        [ "$d" = "/" ] && break
        d=$(dirname "$d")
    done
    return 1
}
_enforced_ctx_down() {  # $1=cwd -> echo nearest descendant context root whose OWN settings enforce
    local cwd="$1" f root
    # ponytail: maxdepth 4 covers projects/<grp>/<proj>/context; raise if projects nest deeper
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        root=$(dirname "$(dirname "$f")")
        grep -q 'PreToolUse' "$root/.claude/settings.json" 2>/dev/null && { printf '%s\n' "$root"; return 0; }
    done < <(find "$cwd" -maxdepth 4 -type f -path '*/context/index.html' 2>/dev/null)
    return 1
}
if [ -n "$cwd" ] && [ -d "$cwd" ]; then
    proj=$(_dir_up_with "$cwd" "context/index.html") || proj=""
    [ -z "$proj" ] && proj=$(_enforced_ctx_down "$cwd")
    if [ -n "$proj" ] && grep -q 'PreToolUse' "$proj/.claude/settings.json" 2>/dev/null; then
        S=$(_dir_up_with "$cwd" ".claude/settings.json") || S=""
        if [ "$S" != "$proj" ]; then
            echo ""
            echo "⚠️ CONTEXT ENFORCEMENT MAY BE OFF: you appear to be working in project $proj"
            echo "   but this session's hooks were resolved from $cwd at launch."
            echo "   If you /cd'd into the project after launch, PreToolUse/lock/validate hooks are NOT loaded."
            echo "   Relaunch inside $proj for deterministic context management."
            echo ""
        fi
    fi
fi
# ----------------------------------------------------------------------------

HOME_DIR="${FIRSTMATE_HOME:-$HOME/.claude/firstmate}"
CTX="$HOME_DIR/context"
[ -f "$CTX/index.html" ] || exit 0   # instance not set up -> silent

echo "=== FIRST-MATE (global context) ==="
echo "Entry point: $CTX/index.html — open a project's own context/ once you route in."

REG="$CTX/project-registry.html"
if [ -f "$REG" ]; then
    echo "--- Projects (registry) ---"
    # Strip tags from registry <article> blocks; handles multi-line and single-line.
    awk '
    /<article/ {
        line=$0; gsub(/<[^>]*>/,"",line); gsub(/^[[:space:]]+|[[:space:]]+$/,"",line)
        if(line!="")print line; a=1; next
    }
    /<\/article>/{a=0;next}
    a {
        line=$0; gsub(/<[^>]*>/,"",line); gsub(/^[[:space:]]+|[[:space:]]+$/,"",line)
        if(line!="")print line
    }' "$REG" 2>/dev/null
fi

DECS="$CTX/decisions"
if [ -d "$DECS" ]; then
    echo "--- Open global execution decisions ---"
    for f in "$DECS"/dec-*.html; do
        [ -f "$f" ] || continue
        status=$(grep -o '<meta name="status" content="[^"]*"' "$f" 2>/dev/null | sed 's/.*content="//;s/"$//')
        case "$status" in superseded|deprecated|rejected) continue;; esac
        title=$(grep -o '<meta name="title" content="[^"]*"' "$f" 2>/dev/null | sed 's/.*content="//;s/"$//')
        [ -n "$title" ] && echo "  - $title"
    done
fi

echo "=== end first-mate ==="
exit 0
