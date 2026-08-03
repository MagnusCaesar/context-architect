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
