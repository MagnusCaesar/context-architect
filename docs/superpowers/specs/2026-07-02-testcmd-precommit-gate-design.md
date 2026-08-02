# Design: testCmd pre-commit gate (block broken code at commit)

Date: 2026-07-02
Status: approved (brainstorm), pending plan

## Context

The enforcement overhaul (DEC-005) closed premature edits, secret leaks, the lock-loop,
and the ledger race. One unguarded failure mode remains: **a subagent can commit broken
code and claim it works.** The code repo's git `pre-commit` currently runs only a
secret-scan; nothing verifies the code actually passes its own tests. The context repo is
gated by `validate.py`, but that only checks doc/ledger structure, not code correctness.

This is the deferred "project `test_cmd` code-correctness gate" — the natural next layer on
top of Layer 2 (the git pre-commit). It closes the last gap per DEC-005's principle:
enforcement is structural (block), not advisory.

**Also in scope (trivial):** strike the already-resolved "firstmate hook reconciliation"
deferred item — the single-source consolidation already made `firstmate/.claude/settings.json`
`{}` with only `session-start-inject.sh` remaining. Verify + strike, no code.

**Explicitly NOT in this spec:** the `check-refs.py` deployment-assumption gate (#5) — it is
a different subsystem (edit-time PreToolUse, not commit-time git hook, no shared code) and
gets its own spec later.

## The change

Add an optional `testCmd` config key. When set, the git `pre-commit` runs it before allowing
a commit and **aborts on failure** (exit 1), like the secret-scan. When unset (default),
nothing changes for that project.

### Where it runs
`hooks/pre-commit` already resolves `CONTEXT_DIR` by checking `$TOP` and `$TOP/context`
(lines 46-52). Reuse that: read `testCmd` from `$CONTEXT_DIR/config.json`. This covers the
common case (context lives under the code repo, e.g. timing-mcp: `$TOP/context/config.json`)
and the context-repo case (`$TOP/config.json`). The test step runs in ANY repo where the
resolved config has a non-empty `testCmd`.

**Known limitation (documented, not fixed):** for a project whose code repo and context dir
sit at unrelated paths (ai-debug-agent: code=`asic-skills`, context=`ai-debug-agent/context`),
the code-repo hook cannot discover the config by filesystem walk, so `testCmd` silently does
not run there — graceful degradation (same as unset). **Upgrade path if needed:** bake the
context-config path into the hook at install time (bootstrap string-substitution). Deferred as
YAGNI until a split-repo project needs the gate.

### The gate logic (added to `hooks/pre-commit` after the secret-scan block, ~line 43,
before or alongside the validate.py block)

```
# --- Optional project test gate: run testCmd from config, abort on failure ---
# (CONTEXT_DIR resolution already exists below for validate.py; reuse it — move that
#  resolution above this block so both steps share it.)
TESTCMD="$(python3 - "$CONTEXT_DIR/config.json" <<'PY' 2>/dev/null
import json,sys
try: print(json.load(open(sys.argv[1])).get("testCmd","") or "")
except Exception: print("")
PY
)"
if [ -n "$TESTCMD" ]; then
    LOG="$(mktemp -t precommit-test.XXXXXX.log)"
    if ! sh -c "$TESTCMD" >"$LOG" 2>&1; then
        echo "pre-commit: tests failed (testCmd: $TESTCMD)" >&2
        # Named failing tests when the runner's format is recognizable (best-effort).
        NAMED="$(grep -nE 'FAILED|✗|^not ok|::.*(FAIL|Error)' "$LOG" | head -10)"
        if [ -n "$NAMED" ]; then
            echo "--- failing ---" >&2
            printf '%s\n' "$NAMED" >&2
        fi
        echo "--- last 40 lines ---" >&2
        tail -40 "$LOG" >&2
        echo "----------------------" >&2
        echo "commit aborted. Fix the failing tests above (re-run just one, e.g. the named test), or bypass with: git commit --no-verify" >&2
        echo "full output: $LOG" >&2
        exit 1
    fi
    rm -f "$LOG"
fi
```

### The "not a chore" contract (hard requirement, per DEC-005 / the 766-plumbing lesson)
The block MUST be self-documenting so the LLM never investigates the hook:
1. **Named failing tests up top** when the runner format is recognizable (grep for
   `FAILED`/`✗`/`not ok`/`::…Error`) — so the agent can re-run just that one test.
2. **Capped tail (~40 lines)** always — the runner's own failure summary, without flooding
   context. Full output path printed for the rare deep case.
3. **The escape hatch in the message** — `git commit --no-verify` for a flaky/unrelated
   failure. The agent is never trapped.

### Config
Add `testCmd` to `templates/config.json` as an authored key with an empty-string default
(`"testCmd": ""`) and a one-line comment-by-convention (JSON has no comments; document in
SKILL.md). Empty = gate disabled. `bootstrap.py` already emits the template; no refresh logic
change needed beyond the key being present.

## Files touched
- `hooks/pre-commit` — add the testCmd gate block; hoist `CONTEXT_DIR` resolution above it so
  the test gate and the existing validate.py block share one resolution.
- `templates/config.json` — add `"testCmd": ""`.
- `SKILL.md` — one line documenting the key (what it is, that empty = off, that failure blocks
  with `--no-verify` escape).
- `deferred_improvements.md` — strike #4 (this) and #3 (firstmate, already done).

## Verification (end-to-end)
1. **Gate off by default:** fresh temp project, `testCmd` unset → commits behave exactly as
   today (secret-scan only). No new friction.
2. **Gate blocks on failing tests:** set `testCmd` to a command that exits non-zero (e.g. a
   1-line `sh -c 'exit 1'` or a trivial failing pytest); stage + commit → aborts (exit 1),
   message shows the tail + the `--no-verify` line. Named-failing section appears for a real
   pytest failure.
3. **Gate passes on green tests:** `testCmd` = a passing command → commit succeeds.
4. **Escape works:** with failing tests, `git commit --no-verify` → succeeds.
5. **No regression:** secret-scan still aborts; context-repo validate.py still runs; smoke
   85/4 unchanged.
6. **Propagation:** `bootstrap.py --refresh` on a project installs the updated hook; verify
   the testCmd block is present in the installed `.git/hooks/pre-commit`.
7. **Firstmate strike:** confirm `firstmate/.claude/settings.json` is `{}` and only
   `session-start-inject.sh` remains, then strike the deferred entry.

## Test approach
A `tests/test_precommit_testcmd.sh` (bash, matches existing `tests/*.sh` style): init a temp
git repo, install the hook, write a config with `testCmd`, and assert: unset→commit ok,
failing→abort+message, passing→ok, `--no-verify`→ok. Self-cleaning temp dirs.
