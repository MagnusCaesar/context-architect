# testCmd Pre-Commit Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `testCmd` config key that makes the git `pre-commit` run a project's own test suite and block the commit on failure, with a self-documenting message.

**Architecture:** Extend the existing `hooks/pre-commit` (already does secret-scan + context-repo `validate.py`). Hoist its `CONTEXT_DIR` resolution above a new test-gate block; read `testCmd` from `$CONTEXT_DIR/config.json`; if non-empty, run it and abort on non-zero exit with named-failing-tests + capped tail + `--no-verify` escape. Unset `testCmd` = no behavior change.

**Tech Stack:** bash (git hook), Python 3 (one-line JSON read), plain-bash test (`tests/*.sh` style: `mktemp -d` + `trap ... EXIT`, `FAIL:`/`exit 1`).

## Global Constraints

- The gate MUST be self-documenting on failure (DEC-005 / 766-plumbing lesson): print (1) named failing tests when the runner format is recognizable (grep `FAILED|✗|not ok|::…Error`), (2) capped tail (~40 lines) always, (3) the `git commit --no-verify` escape, (4) full-output log path. The LLM must never have to investigate the hook.
- Empty/unset `testCmd` = gate disabled; that project's commit behavior is unchanged.
- Blocking, not advisory (exit 1 on test failure) — consistent with the secret-scan and validate.py blocks already in the hook.
- Skill repo is the generator: the hook fix reaches projects only via `bootstrap.py --refresh`. The hook is installed into every `repoRoots[].path` and the context repo.
- No `git push` (user pushes). Commit on the skill repo's current branch.
- Known limitation (documented, not fixed): split-repo projects (code and context at unrelated paths, e.g. ai-debug-agent) — the hook can't discover the config by filesystem walk, so `testCmd` silently does not run there (graceful, same as unset).
- Apply ponytail: reuse the hook's existing `CONTEXT_DIR` resolution; no new script/file beyond the test.

---

### Task 1: testCmd gate in pre-commit + bash test

**Files:**
- Modify: `hooks/pre-commit` (hoist `CONTEXT_DIR` resolution; add test-gate block before the validate.py block)
- Create: `tests/test_precommit_testcmd.sh`

**Interfaces:**
- Consumes: existing `hooks/pre-commit` (secret-scan lines 18-43; `CONTEXT_DIR` resolution lines 46-52; validate.py block lines 54-59).
- Produces: a pre-commit that, when `$CONTEXT_DIR/config.json` has non-empty `testCmd`, runs it and exits 1 on failure with the self-documenting message.

- [ ] **Step 1: Write the failing test**

Create `tests/test_precommit_testcmd.sh`:

```bash
#!/usr/bin/env bash
# Verifies the testCmd pre-commit gate: unset->ok, failing->abort+message, passing->ok, --no-verify->ok.
set -u
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$SKILL/hooks/pre-commit"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

# A context project: config.json lives in the repo root (so CONTEXT_DIR resolves to $TOP).
mk_repo() {  # $1 = testCmd value (may be empty)
  rm -rf "$TMP/p"; mkdir -p "$TMP/p/scripts"; cd "$TMP/p"
  echo '<html><head><title>x</title></head><body></body></html>' > index.html
  printf '{"projectName":"p","testCmd":"%s"}' "$1" > config.json
  # minimal validate.py that always passes, so the validate block never interferes
  printf 'import sys\nsys.exit(0)\n' > scripts/validate.py
  git init -q .; cp "$HOOK" .git/hooks/pre-commit; chmod +x .git/hooks/pre-commit
  git add -A
}

# Case A: testCmd unset -> commit succeeds
mk_repo ""
git commit -q -m init && echo "A ok" || { echo "FAIL A: unset testCmd blocked commit"; exit 1; }

# Case B: testCmd fails -> commit aborts, message shows tail + --no-verify
mk_repo "sh -c 'echo FAILED test_x; exit 1'"
OUT="$(git commit -m init 2>&1)"; RC=$?
[ $RC -ne 0 ] || { echo "FAIL B: failing testCmd did NOT block"; exit 1; }
echo "$OUT" | grep -q -- "--no-verify" || { echo "FAIL B: no escape hatch in message"; exit 1; }
echo "$OUT" | grep -q "test_x" || { echo "FAIL B: failing-test detail not surfaced"; exit 1; }
echo "B ok"

# Case C: --no-verify bypasses the failing gate
git commit -q --no-verify -m init && echo "C ok" || { echo "FAIL C: --no-verify did not bypass"; exit 1; }

# Case D: testCmd passes -> commit succeeds
mk_repo "true"
git commit -q -m init && echo "D ok" || { echo "FAIL D: passing testCmd blocked commit"; exit 1; }

echo "ALL PASS"
```

- [ ] **Step 2: Run test to verify it FAILS on current hook**

Run: `cd /shared/home/vrajagopal/.claude/skills/context-architecture && bash tests/test_precommit_testcmd.sh`
Expected: FAIL at Case B (`FAIL B: failing testCmd did NOT block`) — the current hook has no test gate, so a failing testCmd commits anyway.

- [ ] **Step 3: Hoist CONTEXT_DIR resolution + add the test gate**

In `hooks/pre-commit`: move the `CONTEXT_DIR` resolution block (currently lines 46-52, the `TOP=...` + `for cand in ...` loop) to just after the secret-scan `exit 1` block (after line 43), so both the test gate and the validate.py block can use `CONTEXT_DIR`. Then insert the test gate immediately after that resolution. Result — the region after the secret-scan block becomes:

```bash
# --- Resolve CONTEXT_DIR (shared by test gate + validate.py) ---
TOP="$(git rev-parse --show-toplevel 2>/dev/null)"
CONTEXT_DIR=""
for cand in "$TOP" "$TOP/context"; do
    if [ -f "$cand/index.html" ] && [ -f "$cand/config.json" ] && [ -d "$cand/scripts" ]; then
        CONTEXT_DIR="$cand"; break
    fi
done

# --- Optional project test gate: run testCmd from config, abort on failure ---
if [ -n "$CONTEXT_DIR" ] && [ -f "$CONTEXT_DIR/config.json" ]; then
    TESTCMD="$(python3 - "$CONTEXT_DIR/config.json" <<'PY' 2>/dev/null
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("testCmd", "") or "")
except Exception:
    print("")
PY
)"
    if [ -n "$TESTCMD" ]; then
        LOG="$(mktemp -t precommit-test.XXXXXX.log)"
        if ! sh -c "$TESTCMD" >"$LOG" 2>&1; then
            echo "pre-commit: tests failed (testCmd: $TESTCMD)" >&2
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
fi
```

Then DELETE the now-duplicate `CONTEXT_DIR` resolution that precedes the existing validate.py block (old lines 46-52), leaving the validate.py block (`if [ -n "$CONTEXT_DIR" ] && [ -f "$CONTEXT_DIR/scripts/validate.py" ]; then ...`) to use the hoisted `CONTEXT_DIR`.

- [ ] **Step 4: Run test to verify it PASSES**

Run: `cd /shared/home/vrajagopal/.claude/skills/context-architecture && bash tests/test_precommit_testcmd.sh`
Expected: `A ok`, `B ok`, `C ok`, `D ok`, `ALL PASS`.

- [ ] **Step 5: Regression — secret-scan + validate.py still work, smoke unchanged**

Run: `cd /shared/home/vrajagopal/.claude/skills/context-architecture && bash smoke.sh 2>&1 | grep "=== Results"`
Expected: `85 passed, 4 failed` (4 pre-existing). Then quick secret-scan sanity: init a temp repo, install the hook, stage a file with `sk-` + 20 chars, `git commit` → aborts (proves the hoist didn't break the secret-scan path).

- [ ] **Step 6: Commit**

```bash
cd /shared/home/vrajagopal/.claude/skills/context-architecture
git add hooks/pre-commit tests/test_precommit_testcmd.sh
git commit -m "feat(pre-commit): optional testCmd gate blocks commits on failing project tests"
```

---

### Task 2: config template key + SKILL.md doc

**Files:**
- Modify: `templates/config.json` (add `"testCmd": ""`)
- Modify: `SKILL.md` (one line documenting the key)

**Interfaces:**
- Consumes: the gate from Task 1 (reads `testCmd` from config).
- Produces: `testCmd` present in every newly-bootstrapped project's config with a safe empty default.

- [ ] **Step 1: Add the key to the template**

In `templates/config.json`, add `"testCmd": ""` after the `"maxLinesPerPage": 200,` line (top-level, near the other scalar settings):

```json
  "projectName": "{{PROJECT_NAME}}",
  "maxLinesPerPage": 200,
  "testCmd": "",
  "repoRoots": [
```

- [ ] **Step 2: Verify the template is valid JSON**

Run: `python3 -m json.tool /shared/home/vrajagopal/.claude/skills/context-architecture/templates/config.json >/dev/null && echo VALID`
Expected: `VALID`.

- [ ] **Step 3: Document the key in SKILL.md**

Find the config/settings reference area of `SKILL.md` (search for `maxLinesPerPage` or `config.json`; if there is no config-key list, add the line under the section that first mentions `config.json`). Add one line, verbatim:

```
- `testCmd` (optional, default `""`): a shell command to run the project's tests. When non-empty, the git pre-commit runs it and blocks the commit on failure (named failing tests + tail printed; bypass a flaky/unrelated failure with `git commit --no-verify`). Empty = gate disabled. Resolved from the config next to `context/` (a split code/context layout will not auto-run it).
```

- [ ] **Step 4: Verify SKILL.md still coherent (no broken markdown)**

Run: `grep -n "testCmd" /shared/home/vrajagopal/.claude/skills/context-architecture/SKILL.md`
Expected: the new line appears exactly once.

- [ ] **Step 5: Commit**

```bash
cd /shared/home/vrajagopal/.claude/skills/context-architecture
git add templates/config.json SKILL.md
git commit -m "docs(config): add optional testCmd key + document the pre-commit test gate"
```

---

### Task 3: Propagate to projects + strike resolved deferred items

**Files:**
- Modify (via refresh): each project's `.git/hooks/pre-commit`
- Modify: `/shared/home/vrajagopal/.claude/plans/deferred_improvements.md`

**Interfaces:**
- Consumes: the committed hook (Task 1) + template (Task 2).
- Produces: updated hooks installed in projects; deferred backlog reflects reality.

- [ ] **Step 1: Refresh all four projects, verify the gate landed**

```bash
SKILL=/shared/home/vrajagopal/.claude/skills/context-architecture
for P in /shared/home/vrajagopal/projects/PD/eco_timing \
         /shared/home/vrajagopal/projects/PD/sdc_copilot-dev \
         /shared/home/vrajagopal/projects/PD/timing-mcp \
         /shared/home/vrajagopal/projects/ai-debug-agent; do
  python3 "$SKILL/scripts/bootstrap.py" --target "$P" --refresh >/dev/null 2>&1
  # the code/context repo's installed hook should contain the test-gate marker
  H="$P/context/.git/hooks/pre-commit"
  [ -f "$H" ] && grep -q "testCmd" "$H" && echo "$(basename $P): gate installed" || echo "$(basename $P): CHECK ($H)"
done
```
Expected: each project reports `gate installed` for its context repo. (Code repos where `repoRoots` resolves to a git repo also get it; a `CHECK` on a project whose context repo path differs is expected for the documented split-repo case — note it, don't fail.)

- [ ] **Step 2: Confirm firstmate reconciliation is already done (verify before strike)**

```bash
cat /shared/home/vrajagopal/.claude/firstmate/.claude/settings.json
command ls /shared/home/vrajagopal/.claude/firstmate/context/hooks/*.sh | xargs -n1 basename
```
Expected: settings is `{}`; only `session-start-inject.sh` remains. (If not, STOP — reconciliation is not actually done; escalate.)

- [ ] **Step 3: Strike the two resolved deferred items**

In `/shared/home/vrajagopal/.claude/plans/deferred_improvements.md`:
- Strike the **firstmate hook reconciliation** bullet: prefix its title with `~~…~~` and append `**RESOLVED 2026-07-02** — single-source consolidation left firstmate settings `{}` with only `session-start-inject.sh`; no drift remains.`
- Strike the **Project `test_cmd`** bullet: prefix its title with `~~…~~` and append `**RESOLVED 2026-07-02** — implemented as optional `testCmd` in config; git pre-commit runs it and blocks on failure with self-documenting output. Spec: docs/superpowers/specs/2026-07-02-testcmd-precommit-gate-design.md.`

- [ ] **Step 4: Verify the strike is well-formed**

Run: `grep -c "RESOLVED 2026-07-02" /shared/home/vrajagopal/.claude/plans/deferred_improvements.md`
Expected: `3` (the ledger-race entry already struck + these two).

- [ ] **Step 5: No commit for deferred_improvements.md**

`/shared/home/vrajagopal/.claude/plans/` is outside the skill git repo (and `~/.claude` is not a git repo). No commit here; the edit stands on disk. Project context repos auto-commit via their own Stop hook — do not commit them manually.

## Self-Review

**Spec coverage:** testCmd gate → Task 1; config key + SKILL.md doc → Task 2; propagation → Task 3 Step 1; firstmate verify+strike → Task 3 Steps 2-3; test_cmd deferred strike → Task 3 Step 3; self-documenting-failure contract → Task 1 Step 3 (named + tail + escape + log) and Global Constraints; known split-repo limitation → Global Constraints + Task 3 Step 1 note. `check-refs.py` (#5) correctly absent (separate spec). All spec sections covered.

**Placeholder scan:** no TBD/TODO; every code step shows complete code; commands have expected output.

**Type consistency:** the config key is `testCmd` everywhere (template, hook JSON read, SKILL.md, test); the hook variable is `TESTCMD`; the shared var is `CONTEXT_DIR` in both the hoisted block and the validate.py block. No drift.

**Known caveat captured:** hoisting `CONTEXT_DIR` must DELETE the old duplicate resolution (Task 1 Step 3) or the hook has two identical blocks — called out explicitly. The split-repo graceful-skip is documented, not silently ignored.
