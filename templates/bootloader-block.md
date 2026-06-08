<!-- context-architecture:start -->
## Context Architecture

This repository has a deterministic local context architecture installed under `context/`.

Start here for non-trivial work:

- Read `context/index.html` before broad source exploration.
- Use `context/control-plane.html` to choose read-only, tiny write, or standard write workflow.
- Use `context/ledger.html` for active locks, active source claims, and audit history.
- Use `context/agent-tree.html` only as advisory coordination.
- Use `context/decisions.html`, `context/failure-todos.html`, and `context/open-questions.html` for durable work state.
- Use `context/reproducibility.html`, `context/run-intent.html`, and `context/recognized-commits.html` for execution routing and source/context sync.

Routine context operations are script-owned. When tool permissions allow, run the scripts yourself instead of asking the user:

- `python3 context/scripts/start-task.py --page <page> --intent "<intent>"`
- `python3 context/scripts/route-diff.py --from HEAD~1 --to HEAD`
- `python3 context/scripts/check-freshness.py --json`
- `python3 context/scripts/update-tracks.py --page <page> --add <path>`
- `python3 context/scripts/close-task.py --page <page> --summary "<summary>"`
- `python3 context/scripts/validate.py`

Rules:

- HTML pages under `context/` are source of truth; `docs/context/` is human projection.
- Page-local `<meta name="tracks">` owns source freshness. Missing tracks never means scan the whole repo.
- Ledger is audit history, not durable memory. Durable knowledge belongs in wiki pages and decisions.
- Source claims live as active state in `context/ledger.html`; there is no separate source-claims page.
- Unknown agents default to `readonly`; mutating roles must be explicit in `context/config.json`.
- Prefer context-mode for large analysis, but do not replace deterministic scripts with semantic search.
<!-- context-architecture:end -->
