# Ledger-Race Fix + Single-Source Hook Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serialize the shared-ledger read-modify-write so concurrent auto-acquires can't lose updates, and collapse all Claude Code hooks to a single source directory — validated on ONE canary project against every failure mode before fanning out.

**Architecture:** Fix the skill (the generator) → apply to ONE canary project (sdc_copilot-dev) → stress-test the full failure-mode battery there → fix-loop until green → only then fan out to all projects + global settings → final one-pass sweep everywhere. The ledger fix wraps the read-modify-write inside the two leaf functions (`add_active_lock`, `remove_active_lock`) with a coarse `context_mutex(root, "ledger")` — distinct name from the per-page lock, leaf position guarantees no lock cycle.

**Tech Stack:** Python 3 (stdlib `fcntl`, `multiprocessing`), bash hooks, JSON settings. No new dependencies.

## Execution flow (user-specified — do NOT reorder)

```
Task 1  update skill (ledger fix + test)
Task 2  apply to canary (sdc_copilot-dev) + stress-test ALL failure modes
Task 3  fix-loop: any failure -> fix in skill -> re-run Task 2 -> repeat until 100% green
Task 4  backup ~/.claude config
Task 5  fan out: global hook promotion + firstmate cleanup + refresh remaining 3 projects
Task 6  final sweep: test every project once + independent verifier
```
The canary must be fully green (Task 3 exit) BEFORE Task 5 touches anything else.

## Global Constraints

- Process-safe locking only (single-host); NFS cross-host safety out of scope.
- Ledger mutex name MUST differ from `lock-{page}` — `context_mutex` is NOT reentrant; same-name nesting deadlocks (empirically confirmed, exit 124).
- Skill repo is the generator: `scripts/*.py` fixes reach projects ONLY via `bootstrap.py --refresh` (refresh loop bootstrap.py:562-565 copies every `scripts/*.py` except `bootstrap.py`).
- No `git push` (user pushes). Skill-repo commits on branch `overhaul-enforcement`. Project context repos are the user's / their own Stop-hook's to commit — do NOT commit them.
- `~/.claude` is not a git repo — `tar` backup before editing global settings / deleting firstmate hooks.
- Tests: plain `python3` + `assert`, tempdir setup, no pytest fixtures (match `tests/test_capture_candidates.py`).
- Apply ponytail: shortest working diff, reuse `context_mutex`, no new primitives.
- Canary project = `/shared/home/vrajagopal/projects/PD/sdc_copilot-dev` (context/ is its own git repo; code dir now git-init'd).

---

### Task 1: Update the skill — ledger concurrency test (failing) + leaf-lock fix

**Files:**
- Create: `tests/test_ledger_concurrency.py`
- Modify: `scripts/context_utils.py:424-437` (`add_active_lock`), `scripts/context_utils.py:440-447` (`remove_active_lock`)

**Interfaces:**
- Consumes: `context_mutex(context_root: Path, name: str)` contextmanager (context_utils.py:148).
- Produces: `add_active_lock`/`remove_active_lock` — signatures UNCHANGED; internal `"ledger"` mutex added.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ledger_concurrency.py`:

```python
# tests/test_ledger_concurrency.py
# Concurrency guard for the shared active-locks ledger write.
# Fails on pre-fix code (lost updates); passes once add_active_lock serializes.
import sys, re, multiprocessing as mp
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

from context_utils import add_active_lock  # noqa: E402

LEDGER_SEED = """<html><body>
<section id="active-locks"><table><tbody>
</tbody></table></section>
</body></html>
"""

def _worker(args):
    root, i = args
    add_active_lock(Path(root), f"page{i}.html", f"agent{i}")

def test_concurrent_add_active_lock_no_lost_rows(tmp="/tmp/ledger-conc-test"):
    root = Path(tmp)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".locks").mkdir(exist_ok=True)
    (root / "ledger.html").write_text(LEDGER_SEED)
    n = 16
    with mp.Pool(n) as p:
        p.map(_worker, [(str(root), i) for i in range(n)])
    rows = re.findall(r"<tr>", (root / "ledger.html").read_text())
    assert len(rows) == n, f"expected {n} rows, got {len(rows)} (lost updates = race)"

if __name__ == "__main__":
    test_concurrent_add_active_lock_no_lost_rows()
    print("PASS")
```

- [ ] **Step 2: Run test — verify it FAILS on current code**

Run: `cd /shared/home/vrajagopal/.claude/skills/context-architecture && timeout 60 python3 tests/test_ledger_concurrency.py`
Expected: `AssertionError: expected 16 rows, got <N<16>`.

- [ ] **Step 3: Apply the leaf-lock fix**

In `scripts/context_utils.py`, wrap the read-modify-write in BOTH functions with `context_mutex(context_root, "ledger")` (the `context_root` param is already in scope):

```python
def add_active_lock(context_root: Path, page: str, agent: str, purpose: str = "start-task") -> None:
    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return
    with context_mutex(context_root, "ledger"):
        content = ledger.read_text(errors="replace")
        row = (
            f'          <tr><td>{html.escape(page)}</td><td>{html.escape(agent)}</td>'
            f'<td>{now_utc()}</td><td>{html.escape(purpose)}</td></tr>\n'
        )
        pattern = r'(<section id="active-locks">.*?<tbody>)(.*?)(\s*</tbody>)'
        new_content, count = re.subn(pattern, lambda m: f"{m.group(1)}\n{m.group(2)}{row}{m.group(3)}", content, count=1, flags=re.S)
        if count == 0:
            new_content = content.replace("</tbody>", row + "        </tbody>", 1)
        write_atomic(ledger, new_content, context_root=context_root)


def remove_active_lock(context_root: Path, page: str, agent: str) -> None:
    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return
    with context_mutex(context_root, "ledger"):
        content = ledger.read_text(errors="replace")
        pattern = rf'\s*<tr><td>{re.escape(html.escape(page))}</td><td>{re.escape(html.escape(agent))}</td>.*?</tr>\n?'
        new_content = re.sub(pattern, "", content)
        write_atomic(ledger, new_content, context_root=context_root)
```

- [ ] **Step 4: Run test — verify it PASSES, no deadlock**

Run: `cd /shared/home/vrajagopal/.claude/skills/context-architecture && timeout 60 python3 tests/test_ledger_concurrency.py`
Expected: `PASS` (exit 0). Timeout (124) = deadlock → re-check the mutex name is `"ledger"`.

- [ ] **Step 5: Skill smoke unchanged**

Run: `cd /shared/home/vrajagopal/.claude/skills/context-architecture && bash smoke.sh 2>&1 | grep "=== Results"`
Expected: `85 passed, 4 failed` (4 pre-existing; no new failures, no hang).

- [ ] **Step 6: Commit**

```bash
cd /shared/home/vrajagopal/.claude/skills/context-architecture
git add tests/test_ledger_concurrency.py scripts/context_utils.py
git commit -m "fix(ledger): serialize active-locks RMW with coarse 'ledger' mutex (closes concurrent lost-update race)"
```

---

### Task 2: Canary — apply to sdc_copilot-dev + stress-test ALL failure modes

Apply the updated skill to the ONE canary and run the FULL enforcement battery — not just the ledger fix, but every failure mode the overhaul targets, on a real project. This is the gate before any fan-out.

**Files:**
- Modify (via refresh): `/shared/home/vrajagopal/projects/PD/sdc_copilot-dev/context/scripts/*`, `.../context/hooks/*`
- No source edits here (unless Task 3 loops back).

**Interfaces:**
- Consumes: fixed skill from Task 1.
- Produces: a green/red battery result driving Task 3.

- [ ] **Step 1: Refresh the canary**

```bash
SKILL=/shared/home/vrajagopal/.claude/skills/context-architecture
python3 "$SKILL/scripts/bootstrap.py" --target /shared/home/vrajagopal/projects/PD/sdc_copilot-dev --refresh 2>&1 | tail -4
grep -q 'context_mutex(context_root, "ledger")' /shared/home/vrajagopal/projects/PD/sdc_copilot-dev/context/scripts/context_utils.py && echo "LEDGER FIX PROPAGATED: OK" || echo "MISSING"
```
Expected: files updated, validation PASS, `LEDGER FIX PROPAGATED: OK`.

- [ ] **Step 2: FAILURE MODE — ledger race + deadlock (the new fix)**

Concurrent acquires on DISTINCT pages must not corrupt the ledger and must not hang. Run against the canary's OWN copy:

```bash
C=/shared/home/vrajagopal/projects/PD/sdc_copilot-dev
python3 - <<PY
import sys, re, multiprocessing as mp
from pathlib import Path
sys.path.insert(0, "$C/context/scripts")
from context_utils import add_active_lock
root=Path("$C/context")
def w(i): add_active_lock(root, f"raceprobe{i}.html", f"a{i}")
before=len(re.findall(r"<tr>", (root/"ledger.html").read_text()))
with mp.Pool(12) as p: p.map(w, range(12))
after=len(re.findall(r"<tr>", (root/"ledger.html").read_text()))
print("added", after-before, "expected 12", "-> OK" if after-before==12 else "-> RACE")
PY
# cleanup the probe rows so we don't leave the canary dirty
python3 - <<PY
import sys
from pathlib import Path
sys.path.insert(0,"$C/context/scripts")
from context_utils import remove_active_lock
for i in range(12): remove_active_lock(Path("$C/context"), f"raceprobe{i}.html", f"a{i}")
print("probe rows removed")
PY
timeout 20 python3 "$C/context/scripts/validate.py" >/dev/null 2>&1; echo "validate exit: $? (0 expected)"
```
Expected: `added 12 expected 12 -> OK`; probe rows removed; validate exit 0.

- [ ] **Step 3: FAILURE MODE — lock-loop / auto-acquire (Layer 1)**

5 sequential edits to one context page must force ZERO manual start-task calls (the 766-bleed regression):

```bash
SKILL=/shared/home/vrajagopal/.claude/skills/context-architecture
C=/shared/home/vrajagopal/projects/PD/sdc_copilot-dev
export CLAUDE_SESSION_ID=canary-$$
PAGE=$(ls "$C"/context/*.html | grep -vE 'index|ledger|decisions.html|open-questions.html|failure-todos.html' | head -1)
forced=0
for i in 1 2 3 4 5; do
  printf '{"tool_name":"Edit","cwd":"%s","tool_input":{"file_path":"%s"}}' "$C" "$PAGE" | bash "$SKILL/hooks/pre-edit-context-inject.sh" >/dev/null 2>&1
  [ $? -eq 2 ] && forced=$((forced+1))
done
echo "forced start-task calls: $forced (expect 0)"
grep -o '<meta name="locked" content="[^"]*"' "$PAGE" | head -1
```
Expected: `forced start-task calls: 0`; page `locked=true`.

- [ ] **Step 4: FAILURE MODE — secret-scan (Layer 2) in the canary CONTEXT repo**

```bash
C=/shared/home/vrajagopal/projects/PD/sdc_copilot-dev/context
cd "$C"
printf 'k = "sk-%s"\n' "ABCDEFGH0123456789xy" > .secretprobe.py
git add .secretprobe.py
git commit -q -m "probe" ; echo "commit-with-key exit: $? (expect non-zero)"
git commit -q --no-verify -m "probe-forced" ; echo "no-verify exit: $? (expect 0)"
# clean up the probe commit + file, leave canary as it was
git reset --hard HEAD~1 >/dev/null 2>&1; rm -f .secretprobe.py; echo "probe reverted"
```
Expected: commit-with-key non-zero (aborted), no-verify exit 0, probe reverted.

- [ ] **Step 5: FAILURE MODE — per-file context gate (Layer 3)**

```bash
SKILL=/shared/home/vrajagopal/.claude/skills/context-architecture
C=/shared/home/vrajagopal/projects/PD/sdc_copilot-dev
export CLAUDE_SESSION_ID=canary-gate-$$
UNTRACKED=/tmp/canary-untracked.py; echo x > "$UNTRACKED"
# untracked file -> allow (exit 0)
printf '{"tool_name":"Edit","cwd":"%s","tool_input":{"file_path":"%s"}}' "$C" "$UNTRACKED" | bash "$SKILL/hooks/pre-edit-context-gate.sh" >/dev/null 2>&1
echo "untracked-file gate exit: $? (expect 0)"
rm -f "$UNTRACKED"
```
Expected: `untracked-file gate exit: 0`. (Tracked-file block/allow already unit-proven; this confirms the canary's refreshed gate is the per-file version — `grep -q "tracking page(s) for this file" "$C/context/hooks/pre-edit-context-gate.sh" && echo GATE-VERSION-OK`.)

- [ ] **Step 6: Record battery result**

Tabulate Steps 2-5 as PASS/FAIL. If ALL pass → canary green, skip Task 3, go to Task 4. If ANY fail → go to Task 3.

- [ ] **Step 7: Leave the canary clean**

Confirm: `cd /shared/home/vrajagopal/projects/PD/sdc_copilot-dev/context && git status --short` shows no probe artifacts (the auto-commit Stop hook may have committed legitimate ledger churn — that's fine; only ensure no `.secretprobe`/`raceprobe` residue).

---

### Task 3: Fix-loop until canary is 100% green

Only entered if Task 2 found a failure. This is a LOOP, not a one-shot.

- [ ] **Step 1: Diagnose the failing mode** — identify which battery step failed and whether the root cause is in the skill source (`scripts/` or `hooks/`) or the test harness.
- [ ] **Step 2: Fix in the SKILL source** (never patch only the project copy — the skill is the generator). Apply ponytail: smallest diff at root cause.
- [ ] **Step 3: Commit the fix** on `overhaul-enforcement` with a message naming the failure mode.
- [ ] **Step 4: Re-run Task 2 from Step 1** (re-refresh canary + full battery). 
- [ ] **Step 5: Repeat Steps 1-4 until every battery step PASSES.** Do not proceed to Task 4 with any red.

---

### Task 4: Back up ~/.claude config (before global edits)

**Files:** Create `/tmp/claude-config-backup-part2.tgz`

- [ ] **Step 1: Tar the non-git config surface**

```bash
cd /shared/home/vrajagopal/.claude
tar czf /tmp/claude-config-backup-part2.tgz \
  settings.json settings.local.json \
  firstmate/.claude/settings.json firstmate/context/hooks/
echo "backup exit: $?"; tar tzf /tmp/claude-config-backup-part2.tgz | head
```
Expected: exit 0; listing shows settings + firstmate hooks. Only revert path for Part 2.

---

### Task 5: Fan out — global hook promotion + firstmate cleanup + refresh remaining projects

Canary is green. Now apply everywhere.

**Files:**
- Modify: `~/.claude/settings.json` (add Stop/SubagentStop/SubagentStart)
- Modify: `~/.claude/firstmate/.claude/settings.json` (remove `hooks` block)
- Delete: `~/.claude/firstmate/context/hooks/*.sh` EXCEPT `session-start-inject.sh`
- Modify (via refresh): eco_timing, timing-mcp, ai-debug-agent project copies

- [ ] **Step 1: Confirm the 3 promoted hooks exist in the skill dir**

```bash
H=/shared/home/vrajagopal/.claude/skills/context-architecture/hooks
for f in auto-commit-context.sh capture-on-stop.sh subagent-start-inject.sh; do
  test -f "$H/$f" && echo "EXISTS $f" || echo "MISSING $f"
done
```
Expected: all three EXISTS.

- [ ] **Step 2: Add the three events to global settings.json (preserve existing keys)**

Edit `~/.claude/settings.json`, adding under the existing `"hooks"` object:

```json
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "bash /shared/home/vrajagopal/.claude/skills/context-architecture/hooks/auto-commit-context.sh" },
        { "type": "command", "command": "bash /shared/home/vrajagopal/.claude/skills/context-architecture/hooks/capture-on-stop.sh" }
      ] }
    ],
    "SubagentStop": [
      { "hooks": [
        { "type": "command", "command": "bash /shared/home/vrajagopal/.claude/skills/context-architecture/hooks/auto-commit-context.sh" }
      ] }
    ],
    "SubagentStart": [
      { "hooks": [
        { "type": "command", "command": "bash /shared/home/vrajagopal/.claude/skills/context-architecture/hooks/subagent-start-inject.sh" }
      ] }
    ]
```

- [ ] **Step 3: Validate + safety-probe the promoted hooks**

```bash
python3 -m json.tool /shared/home/vrajagopal/.claude/settings.json >/dev/null && echo "global VALID"
H=/shared/home/vrajagopal/.claude/skills/context-architecture/hooks
for f in auto-commit-context.sh capture-on-stop.sh subagent-start-inject.sh; do
  echo '{"cwd":"/tmp"}' | bash "$H/$f"; echo "$f non-context exit: $?"
done
```
Expected: `global VALID`; every hook exit 0 from a non-context cwd (must never block globally).

- [ ] **Step 4: firstmate — confirm equivalents, then strip wiring**

```bash
FM=/shared/home/vrajagopal/.claude/firstmate/context/hooks
SK=/shared/home/vrajagopal/.claude/skills/context-architecture/hooks
for f in "$FM"/*.sh; do b=$(basename "$f"); test -f "$SK/$b" && echo "OK $b" || echo "NO-EQUIV $b"; done
```
Expected: `OK` for all. Any `NO-EQUIV` → keep that file, flag it.
Then edit `~/.claude/firstmate/.claude/settings.json` to remove the entire `"hooks"` block (keep other keys; likely becomes `{}`).
Validate: `python3 -m json.tool ~/.claude/firstmate/.claude/settings.json && echo VALID`.

- [ ] **Step 5: Delete orphaned firstmate copies — EXEMPT session-start-inject.sh**

`session-start-inject.sh` is still referenced from GLOBAL SessionStart — do NOT delete it.

```bash
FM=/shared/home/vrajagopal/.claude/firstmate/context/hooks
find "$FM" -maxdepth 1 -name '*.sh' ! -name 'session-start-inject.sh' -delete
ls "$FM"/*.sh 2>/dev/null | xargs -n1 basename
grep -q "firstmate/context/hooks/session-start-inject.sh" /shared/home/vrajagopal/.claude/settings.json \
  && test -f "$FM/session-start-inject.sh" && echo "session-start PRESERVED + wired"
```
Expected: only `session-start-inject.sh` listed; `session-start PRESERVED + wired`.

- [ ] **Step 6: Refresh the remaining 3 projects (canary already done)**

```bash
SKILL=/shared/home/vrajagopal/.claude/skills/context-architecture
for P in /shared/home/vrajagopal/projects/PD/eco_timing \
         /shared/home/vrajagopal/projects/PD/timing-mcp \
         /shared/home/vrajagopal/projects/ai-debug-agent; do
  echo "=== $P ==="
  python3 "$SKILL/scripts/bootstrap.py" --target "$P" --refresh 2>&1 | tail -2
  grep -q 'context_mutex(context_root, "ledger")' "$P/context/scripts/context_utils.py" && echo "ledger fix: OK" || echo "ledger fix: MISSING"
done
```
Expected: each updated, validation PASS, `ledger fix: OK`.

---

### Task 6: Final sweep — test every project once + independent verifier

- [ ] **Step 1: Ledger fix present in all 4 projects + skill**

```bash
grep -q 'context_mutex(context_root, "ledger")' /shared/home/vrajagopal/.claude/skills/context-architecture/scripts/context_utils.py && echo "skill OK"
for P in eco_timing sdc_copilot-dev timing-mcp; do
  grep -q 'context_mutex(context_root, "ledger")' /shared/home/vrajagopal/projects/PD/$P/context/scripts/context_utils.py && echo "$P OK" || echo "$P MISSING"
done
grep -q 'context_mutex(context_root, "ledger")' /shared/home/vrajagopal/projects/ai-debug-agent/context/scripts/context_utils.py && echo "ai-debug-agent OK" || echo "MISSING"
```
Expected: all OK.

- [ ] **Step 2: Skill concurrency test + smoke green**

```bash
cd /shared/home/vrajagopal/.claude/skills/context-architecture
timeout 60 python3 tests/test_ledger_concurrency.py && echo "conc PASS"
bash smoke.sh 2>&1 | grep "=== Results"
```
Expected: `conc PASS`; `85 passed, 4 failed`.

- [ ] **Step 3: Single hook source + global settings valid**

```bash
python3 -m json.tool /shared/home/vrajagopal/.claude/settings.json >/dev/null && echo "global VALID"
ls /shared/home/vrajagopal/.claude/firstmate/context/hooks/*.sh 2>/dev/null | xargs -n1 basename
```
Expected: `global VALID`; only `session-start-inject.sh` remains.

- [ ] **Step 4: One quick failure-mode spot-check per remaining project**

For eco_timing, timing-mcp, ai-debug-agent: run the Task 2 Step 2 ledger-race probe (adjust `$C` path) → expect `added 12 -> OK` + validate exit 0. This confirms the fix works on each real project, not just the canary.

- [ ] **Step 5: Independent verifier subagent**

Dispatch a fresh subagent with NO design context: hand it Task 6 Steps 1-4 as a checklist, have it re-run on a clean tree and return a PASS/FAIL table. Do not accept implementer self-reports alone.

## Self-Review

**Spec coverage:** ledger fix → Task 1; propagation-is-required → Tasks 2 & 5 & 6 (refresh + grep verify); canary-first flow → Tasks 2-3 (user-specified); global promotion → Task 5; firstmate cleanup + copy deletion → Task 5; backup → Task 4; final everywhere-once → Task 6. All spec sections + user flow covered.

**Placeholder scan:** no TBD/TODO; every code step shows real code/commands with expected output.

**Type consistency:** `add_active_lock`/`remove_active_lock` signatures unchanged; `context_mutex(context_root, "ledger")` string identical in Task 1 and all grep-verifies (Tasks 2/5/6). No drift.

**Known footguns captured:** (1) `session-start-inject.sh` is a `.sh` still wired globally — Task 5 Step 5 uses `! -name` to exempt it from the delete. (2) Canary probes clean up after themselves (Task 2 Steps 2/4/7) so the real project isn't left dirty. (3) Fan-out is gated behind a fully-green canary (Task 3 exit).
