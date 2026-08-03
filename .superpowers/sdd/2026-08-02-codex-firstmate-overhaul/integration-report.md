# Lane integration report

## Inputs

- Main lane: `9b5c649`
- Adapter lane: `cad3756`
- Merge mode: `git merge --no-ff codex-firstmate-adapter`
- Conflict: `scripts/bootstrap.py` only, as expected

## Resolution

- Preserved canonical context-root, history, locator, typed graph, platform,
  hook, Firstmate, and model-refresh flows.
- Platform and locator failures preflight before writes.
- Linked-worktree hook commands point at the canonical context scripts/root.
- Dispatcher uses `build_capsule`, `record_receipt`, and `restore_capsule`.
- Claude and Codex `SubagentStart` `additionalContext` equals only
  `capsule.text`; no private status/diagnostic/receipt envelope is appended.
- Firstmate resolves one registered canonical project, then expresses its route
  inside the task capsule input.
- Post-compact restore reads the canonical ledger and rebuilds changed source
  hashes with restoration lineage.
- Hook edit auto-lock calls the shared lock core directly; it never executes
  `start-task.py` or exposes task-start diagnostics.
- Task 10 release/docs work was not performed.

## TDD evidence

- RED: `tests/test_capsule_hook_integration.py` initially failed `4/4` for
  linked hook paths, canonical capsule protocol, ledger restoration, and
  Firstmate routing.
- GREEN: integration file `5/5`, including actual Claude and Codex CLI JSON
  protocol output.

## Verification

- Focused integration: `154 passed`.
- Full Python suite: `199 passed`.
- Smoke: `101 passed, 0 failed`.
- Python compile: `28` scripts, exit `0`.
- Bash syntax: `6` files, `0` failures.
- `git diff --cached --check`: exit `0`.
- `git diff --check`: exit `0`.

## Concerns deferred to later plan tasks

- Live installed Codex/Claude hook execution remains Task 11.
- Release/changelog/package gates remain Task 10.

## Fix round 1

- Migration rejects source-root and nested symlinks before copy; source,
  outside data, and target remain unchanged on failure.
- Stop/SessionEnd appends one escaped 500-character candidate through the
  shared inbox mutex for Claude and Codex, emits no model context, and restores
  inbox mode to `0600` after atomic replacement.
- Unsupported `autoCommitContext` is absent on bootstrap and removed on
  refresh; no auto-commit behavior is claimed.
- Linked-worktree edits accept absolute paths only inside the Git worktree or
  verified canonical context. Absolute outside paths and source/context
  symlink escapes fail before shared read/lock gates; canonical page edits keep
  lock-owner enforcement.
- Global bootstrap resolves and preflights platform adapters before mkdir or
  Git initialization. Failed refresh and ambiguous generate/init leave a
  nonexistent target absent.

### Fix-round TDD evidence

- Symlink migration RED `2/2`; Firstmate GREEN `15/15`.
- Stop capture/config RED `3/3`; capture/config GREEN `9/9`.
- Linked absolute-path RED `3/3`; hook integration GREEN `35/35`.
- Global preflight RED `3/3`; platform GREEN `24/24`.

### Fix-round verification

- Focused findings: `94 passed`.
- Full Python suite: `210 passed`.
- Smoke: `101 passed, 0 failed`.
- Python compile: `28` scripts, exit `0`.
- Bash syntax: `6` files, `0` failures.
- `git diff --check`: exit `0`.

## Fix round 2

- Claude Stop and Codex SessionEnd normalize the documented
  `last_assistant_message` field. Stop alone retains `final_message` as a
  backward-compatible fallback.
- SessionEnd never opens `transcript_path`; reason/transcript-only payloads
  cannot append candidates. An explicit documented last assistant message can
  append through the existing bounded, redacted, mutex-protected `0600` inbox
  path.
- Adversarial outside, symlink, traversal-shaped, and multi-megabyte transcript
  sentinels prove zero transcript reads and zero candidates.

### Fix-round 2 TDD evidence

- Documented Stop/SessionEnd capture RED `2/2`, then GREEN `2/2`.
- Transcript-only adversaries remained safe `3/3`; combined targeted suite
  GREEN `30/30`.
- Legacy `final_message` is characterized as a Stop-only fallback `1/1`.

### Fix-round 2 verification

- Focused hook/lifecycle suite: `84 passed`.
- Full Python suite: `214 passed`.
- Smoke: `101 passed, 0 failed`.
- Python compile: `28` scripts, exit `0`.
- Bash syntax: `6` files, `0` failures.
- `git diff --check`: exit `0`.
