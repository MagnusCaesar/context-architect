# Design: Ledger-race fix + single-source hook consolidation

Date: 2026-07-02
Status: approved (brainstorm), pending plan

## Context

Two follow-ups from the enforcement overhaul (`overhaul-enforcement` branch):

1. **Ledger race (bug).** `add_active_lock`/`remove_active_lock` do a read-modify-write
   on the shared `context/ledger.html` active-locks table, but the only lock held during
   acquire is per-page (`context_mutex(root, "lock-{page}")`). Concurrent acquires on
   *different* pages take *different* mutexes, so they don't serialize against the shared
   ledger write → lost updates. Layer 1 (auto-acquire on every edit) makes concurrent
   acquires far more common, so this latent bug now bites in practice.

   **Empirically confirmed** (throwaway probe against the real `context_utils.context_mutex`):
   - Per-page-only, 12 concurrent writers to a shared counter → **expected 12, got 1**
     (11 lost updates). Race is real and severe.
   - `context_mutex` is **NOT reentrant**: nesting the *same* name in one process
     **deadlocks** (timed out, exit 124). → the new lock MUST use a name distinct from
     `lock-{page}`.
   - Distinct-name nesting completes cleanly (exit 0).
   - Leaf fix (inner `context_mutex(root, "ledger")` around the RMW) → **expected 12,
     got 12**, no deadlock. Fix works.

2. **Hook drift (cleanup).** Hooks should have ONE source directory. Verified state:
   - Global `~/.claude/settings.json` fires the PreToolUse/PostToolUse gates from the
     skill dir (`~/.claude/skills/context-architecture/hooks/`) — good, already global.
   - `~/.claude/firstmate/.claude/settings.json` ALSO wires 10 hooks from its own
     `firstmate/context/hooks/` copies, and is the ONLY place `Stop`, `SubagentStop`,
     `SubagentStart` are wired (auto-commit-context, capture-on-stop, subagent-start-inject).
     These only fire when cwd is under `~/.claude/firstmate` today.
   - Project settings already pruned of hooks (clean).

   **Decision (user):** promote the Stop/SubagentStop/SubagentStart hooks to GLOBAL so
   auto-commit + subagent-inject fire for all context projects, and make firstmate carry
   zero local hook wiring → one source directory (skill dir) for everything.
   Safe because: `auto-commit-context.sh` refuses code repos (commits only `context/`),
   `capture-on-stop.sh` is advisory (exit 0), `subagent-start-inject.sh` no-ops outside
   context projects.

**Intended outcome:** concurrent auto-acquires never corrupt the ledger; every Claude
Code hook resolves to the single skill-dir source; firstmate keeps no hook copies.

## Part 1 — Ledger race fix

**Change:** wrap the read-modify-write inside `add_active_lock` and `remove_active_lock`
(`scripts/context_utils.py`, ~L424 and ~L445) with `with context_mutex(context_root,
"ledger"):`. The lock is placed INSIDE the leaf functions (not at call sites) so every
caller is protected automatically.

**Why correct + deadlock-free (proven, not assumed):**
- Name `"ledger"` ≠ `"lock-{page}"` → no same-name self-deadlock (the reentrancy hang
  confirmed above).
- These are LEAF functions — they acquire no other lock — so they can never be part of a
  lock cycle regardless of caller (resource-ordering: a leaf can't close a cycle).
- Callers that already hold `lock-{page}` (acquire path) now nest `page → ledger`, always
  in that order → single global order → no cycle.

**Scope:** process-safe via existing `fcntl`-based `context_mutex`. Single-host only
(user works on one machine); NFS cross-host safety explicitly out of scope (YAGNI).

**Reuse:** `context_mutex` (context_utils.py:148) — no new primitive, no `flock(1)`
shell-out (in-process fcntl already provides it). Diff ≈ two `with` wrappers.

**Check to leave behind:** `tests/test_ledger_concurrency.py` — bootstrap a temp context,
spawn N (≥12) concurrent `add_active_lock` calls on DISTINCT pages, assert the active-locks
`<tbody>` ends with exactly N rows and `validate.py` passes. This test FAILS on today's
code and PASSES after the fix (independent verification of the fix).

## Part 2 — Single-source hook consolidation

**Changes:**
1. **Promote to global** `~/.claude/settings.json` — add three events, all pointing at
   `~/.claude/skills/context-architecture/hooks/`:
   - `Stop` → `auto-commit-context.sh`, `capture-on-stop.sh`
   - `SubagentStop` → `auto-commit-context.sh`
   - `SubagentStart` → `subagent-start-inject.sh`
   Preserve existing global entries (SessionStart cache-heal.mjs + firstmate
   session-start-inject.sh, and the existing Pre/Post gates). Validate JSON parses.
2. **Firstmate wiring removed** — `~/.claude/firstmate/.claude/settings.json`: delete its
   `hooks` block entirely (global now covers every event it wired). SessionStart's
   firstmate `session-start-inject.sh` stays referenced from GLOBAL settings, so firstmate
   context injection is preserved.
3. **Delete firstmate's hook copies** — `~/.claude/firstmate/context/hooks/*.sh` (now
   orphaned). Confirm each has a skill-dir equivalent before deleting; flag any that
   don't. (These are firstmate-owned copies, not the skill source.)

**Backup:** `~/.claude` is not a git repo. Before editing global settings / deleting
firstmate hooks, `tar czf /tmp/claude-config-backup-part2.tgz` the global `settings.json`,
`settings.local.json`, `firstmate/.claude/settings.json`, and `firstmate/context/hooks/`.
Revert = untar. (Skill-dir changes are git-tracked on the branch.)

## Propagation (the skill repo is the generator)

The context-architecture skill repo is the SOURCE that `bootstrap.py` uses to build the
`context/` plumbing into every project (scripts, hooks, ledger machinery) from bare. Each
project therefore holds a *copy* of `context_utils.py` and the hooks under its own
`context/scripts/` and `context/hooks/`. A fix to the skill repo does NOT reach projects
until `bootstrap.py --refresh` overwrites those skill-owned copies.

**Therefore the fix is not "done" at the skill edit — it is done when propagated:**
- After the ledger fix lands in `scripts/context_utils.py`, run
  `bootstrap.py --target <p> --refresh` for all 4 projects (eco_timing, sdc_copilot-dev,
  timing-mcp, ai-debug-agent) so each project's `context/scripts/context_utils.py` gets
  the fixed version. Verify by grepping the `"ledger"` mutex in each project's copy.
- `--refresh` overwrites skill-owned scripts/hooks but does NOT delete files removed from
  the skill (confirmed earlier: retired `pre-edit-lock-check.sh` lingered). So firstmate's
  deleted hook copies (Part 2 step 3) must be removed manually per location; they won't be
  recreated by refresh since the skill no longer wires them.
- The concurrency test (`tests/test_ledger_concurrency.py`) lives in the skill repo and
  runs against the skill's own `scripts/`, guarding the source of truth.

## Not in scope
- NFS cross-host lock safety (single-host use).
- Deployment-model / `check-refs.py` gate (deferred; separate item).
- Project `test_cmd` code-correctness gate (deferred; natural next layer on Layer 2).
- Worktree standing-rule in `orchestrate` (separate small doc edit; noted, not bundled).

## Verification (end-to-end)
1. **Race:** run `tests/test_ledger_concurrency.py` → fails on baseline, passes after fix.
   Also run the fix under `timeout` to prove no deadlock (a hang = fail).
2. **No-deadlock regression:** `smoke.sh` still 85 pass / 4 (pre-existing) fail — no new
   failures, no hang.
3. **Consolidation:** `python3 -m json.tool` on global + firstmate settings → valid.
   Every hook command in global settings references an existing skill-dir file.
   `ls ~/.claude/firstmate/context/hooks/` → empty of `.sh` (or only flagged non-equivalents).
   Pipe representative stdin JSON to the newly-global Stop/SubagentStart hooks from a
   context-project cwd → run; from a non-context cwd → exit 0 no-op.
4. **Commit:** per-part commits on `overhaul-enforcement` (ledger fix + test = one; each
   is independently revertable). No push.
