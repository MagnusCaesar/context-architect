#!/usr/bin/env bash
# auto-commit-context.sh — Stop / SubagentStop hook. When the editing agent finishes
# its turn, deterministically commits the context/ repo it touched so agents never
# have to ask. The commit fires the post-commit hook, which auto-releases that page's
# lock (edit -> finish -> commit -> unlock). Advisory: always exit 0.
#
# Scope guard: only ever runs git inside a context/ repo (a dir whose git toplevel
# ends in /context). It NEVER commits the parent project/code repo — that stays an
# explicit human decision. Gated by config.json "autoCommitContext" (default true).
set -u
INPUT="$(cat 2>/dev/null)"
CWD="$(printf '%s' "$INPUT" | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('cwd',''))
except Exception: print('')" 2>/dev/null)"
[ -n "$CWD" ] || CWD="$PWD"

FM_HOME="${FIRSTMATE_HOME:-$HOME/.claude/firstmate}"

# Commit one context repo if it is dirty and the flag allows it.
# Safe iff the git toplevel is PROVABLY code-free: either it IS the context dir
# itself (project layout: context/ is its own repo), or it IS the trusted
# first-mate home (global instance: a dedicated, code-free context-arch repo).
# A project's parent code repo can match neither, so code is never committed.
commit_ctx() {
    ctx="$1"
    [ -d "$ctx" ] || return 0
    [ -f "$ctx/index.html" ] || return 0          # must look like a context dir
    [ -f "$ctx/config.json" ] || return 0
    # Flag gate: default true; only skip if explicitly false.
    flag=$(python3 -c "import json;print(json.load(open('$ctx/config.json')).get('autoCommitContext', True))" 2>/dev/null)
    [ "$flag" = "False" ] && return 0
    top=$(git -C "$ctx" rev-parse --show-toplevel 2>/dev/null) || return 0
    ctx_abs=$(cd "$ctx" 2>/dev/null && pwd) || return 0
    fm_abs=$(cd "$FM_HOME" 2>/dev/null && pwd 2>/dev/null || echo "")
    # Allowed only if toplevel is the context dir, or the trusted firstmate home
    # whose context/ is exactly this dir.
    if [ "$top" != "$ctx_abs" ] \
       && ! { [ -n "$fm_abs" ] && [ "$top" = "$fm_abs" ] && [ "$ctx_abs" = "$fm_abs/context" ]; }; then
        return 0   # refuse: would commit a repo larger than the context dir (e.g. code)
    fi
    # Nothing to do if clean.
    git -C "$top" diff --quiet 2>/dev/null && git -C "$top" diff --cached --quiet 2>/dev/null \
        && [ -z "$(git -C "$top" ls-files --others --exclude-standard)" ] && return 0
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)
    # ponytail: serialize commits across concurrent Stop hooks with flock(-w 10).
    # Concurrent `git add -A` + commit in one repo race the index lock; on timeout
    # skip (return 0) rather than hang or error the Stop hook.
    mkdir -p "$top/.locks" 2>/dev/null
    ( flock -w 10 9 || { echo "[auto-commit] commit lock busy, skipped" >&2; exit 0; }
      git -C "$top" add -A 2>/dev/null
      git -C "$top" commit -q -m "context: auto-commit at session end ($ts)" 2>/dev/null \
          && echo "[auto-commit] committed context at $top" >&2
    ) 9>"$top/.locks/git-commit.lock"
}

# 1) The project the session is working in (tree-walk up from cwd for a context/).
CHECK="$CWD"
while [ "$CHECK" != "/" ] && [ -n "$CHECK" ]; do
    if [ -f "$CHECK/context/index.html" ]; then commit_ctx "$CHECK/context"; break; fi
    if [ -f "$CHECK/index.html" ] && [ -f "$CHECK/config.json" ]; then commit_ctx "$CHECK"; break; fi
    CHECK="$(dirname "$CHECK")"
done

# 2) The global first-mate instance (often touched during a session).
commit_ctx "${FIRSTMATE_HOME:-$HOME/.claude/firstmate}/context"

exit 0
