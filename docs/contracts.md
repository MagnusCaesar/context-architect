# Context Architecture Contracts

This file defines script-owned contracts for the lean V1 context architecture.
Scripts report facts and enforce structure. The orchestrator resolves judgment:
blocked locks, stale context, unmatched files, and whether new durable pages are
justified.

## Status Contracts

- `start-task.py`: `acquired`, `blocked_active_lock`, `broke_stale_lock`
- `close-task.py`: `released`, `release_denied_wrong_owner`, `validation_warning`
- `check-freshness.py`: `fresh`, `stale`, `untracked`
- `route-diff.py`: top-level `matched_pages`, `unmatched_files`, `stale_tracks`
- `check-reachability.py`: `ok`, `warning`, `orphans_found`
- `daily-hygiene.py`: `ok`, `warning`, `critical`, `skipped`

Existing JSON fields should be preserved where practical. New callers should use
the stable `status` field.

## Page Metadata

`tracks` is the deterministic page-to-source mapping:

```html
<meta name="tracks" content="src/parser.py, tests/test_parser.py">
```

Rules:

- Paths are relative to the configured repo root.
- Entries are comma-separated.
- Python `fnmatch` shell-style globs are allowed.
- `context-only` means the page is maintained by wiki/decision work and has no
  repo-source freshness owner.
- Empty or missing `tracks` means `untracked`; scripts must not fall back to
  scanning the whole repo.

`reviewed-at` is an optional UTC timestamp updated by `close-task.py` after a
successful task close:

```html
<meta name="reviewed-at" content="2026-06-06T12:00:00Z">
```

## Ledger Events

`ledger.html` keeps the current active-lock table and also contains:

```html
<section id="events">
```

Event rows are structured HTML. Visible columns are:

`time`, `event`, `page`, `agent`, `status`, `details`

Rows also carry matching `data-*` attributes so validators can parse them
deterministically.

The first non-`daily_hygiene` ledger event of a local day silently runs daily
hygiene before appending the requested event. Hygiene appends exactly one
`daily_hygiene` event per day. It does not delete, archive, or spawn agents.

## Reachability

Reachability answers whether a fresh agent can discover a context page from the
bootloader or head page. It is separate from freshness tracking.

Root priority:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `.agents/AGENTS.md`
4. `context/index.html`
5. future context-map aliases

The checker inventories live `context/**/*.html`, excluding `context/archived/**`
and `context/docs/**`, then uses BFS over bootloader context references and
internal HTML links. `tracks`, ledger events, and decision refs are not
reachability edges.

Broken internal links are critical. Orphans and fallback roots are warnings.

## Decision Graph

Decision entries are durable rationale, not event history. Each decision article
must include `data-status` and these fields:

- `Question`
- `Decision`
- `Rationale`
- `Consequences`
- `Review when`

Optional attributes:

- `data-builds-on`
- `data-tracks`

## Memory Boundary

Ledger events are audit history, not durable semantic memory. Durable knowledge
belongs in wiki pages and decisions. Create a new page only when no existing
page owns the topic, the knowledge is durable, and there is a future read
trigger.

Scripts detect facts. The orchestrator proposes context changes. The user or an
authorized agent approves new pages and destructive cleanup.
