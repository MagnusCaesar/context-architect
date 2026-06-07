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
- `record-agent.py`: `recorded`, `permission_denied`
- mutating scripts may return `permission_denied`

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

`ledger-events.ndjson` is the append-only event source of truth. Each line is
one JSON object with:

`time`, `event`, `page`, `agent`, `status`, `details`

Optional event attributes live under `extra_attrs`.

`ledger.html` keeps the current active-lock table and renders a bounded recent
window from `ledger-events.ndjson`:

```html
<section id="events">
```

Rendered event rows are structured HTML. Visible columns are:

`time`, `event`, `page`, `agent`, `status`, `details`

Rows also carry matching `data-*` attributes so validators can parse them
deterministically.

`ledgerRenderLimit` in `config.json` bounds rendered rows in `ledger.html` so
the context page does not grow without limit. The NDJSON log may keep full audit
history.

The first non-`daily_hygiene` ledger event of a local day silently runs daily
hygiene before appending the requested event. Hygiene appends exactly one
`daily_hygiene` event per day. It does not delete, archive, or spawn agents.

`harden-ledger.sh` may set `chattr +a` on `ledger-events.ndjson` when Linux and
the filesystem support it. Run it as `root`, an elevated user, or another Unix
user that the agent cannot control. If the agent can run `chattr -a`, hardening
is advisory only. Scripts must still work without it.

`check-hardening.py` reports whether append-only and runtime-boundary
assumptions are actually true for the current process.

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

## Agent Tree

`agent-tree.html` is advisory coordination, not lock authority. It helps agents
see active subagent work before escalating to the orchestrator. Lock authority
remains page lock metas plus the ledger active-lock table.

`record-agent.py` upserts one row per `agent-id` and renders a tree from
`parent-id`. Inputs:

`agent-id`, `parent-id`, `role`, `task`, `page`, `status`, `details`

Statuses:

- `spawned`
- `active`
- `blocked`
- `handoff`
- `closed`

Lifecycle statuses `spawned`, `blocked`, `handoff`, and `closed` also append a
ledger event. `active` refreshes update only `agent-tree.html`.

## Permissions

`SKILL.md` declares the permission profile template in frontmatter.
`bootstrap.py` seeds those defaults into `context/config.json`. Scripts enforce
`config.json`; the skill file itself is only declaration.

Script permissions are workflow enforcement, not an OS sandbox. To prevent an
agent from bypassing scripts, the runtime must deny dangerous commands and/or
protected file writes as described in `context/runtime-policy.md`.

Default roles:

- `orchestrator`: acquire/release locks, break stale locks, force release,
  update tracks, record any agent.
- `worker`: acquire free locks, release own locks, record itself.
- `readonly`: run read-only checks only.

Unknown agents default to `readonly`. `agentRoles` in `config.json` maps
explicit agent IDs to mutating roles.

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
