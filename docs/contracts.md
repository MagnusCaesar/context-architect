# Context Architecture Contracts

Codex version, hook/subagent observations, model availability, and known gaps are tracked in [Codex compatibility](codex-compatibility.md); this file remains the harness-neutral behavioral authority.

This file defines script-owned contracts for the lean V1 context architecture.
Scripts report facts and enforce structure. The orchestrator resolves judgment:
blocked locks, stale context, unmatched files, and whether new durable pages are
justified.

## Status Contracts

| Script | Stable output contract |
|--------|------------------------|
| `bootstrap.py` | JSON `status: error` for rejected inputs; scan/generate modes otherwise print structured findings or generation summary. `--platform claude`, `codex`, or `both` selects managed `CLAUDE.md`, `AGENTS.md`, or both; ambiguous detection fails before writes. Generate and refresh preflight every selected managed block before mutation, and refresh reuses the platform stored in `context/config.json`. |
| `start-task.py` | JSON `status`: `acquired`, `blocked_active_lock`, `broke_stale_lock`, `read_only`, `error`; also returns `task_class` where applicable. |
| `close-task.py` | JSON `status`: `released`, `release_denied_wrong_owner`, `validation_warning`, `error`; validation warnings keep the lock. |
| `check-freshness.py` | JSON `status`: `fresh`, `stale`, `untracked`, `unknown`, `error`. `unknown` means git/source state could not be proven. |
| `route-diff.py` | JSON top-level keys: `matched_pages`, `affected_decisions`, `unmatched_files`, `stale_tracks`, `untracked_pages`; may return `status: error` on fatal input/git failures. |
| `update-tracks.py` | JSON `status`: `updated`, `unchanged`, `error`; mutating calls may return `permission_denied`. |
| `check-failure-todos.py` | JSON `status`: `clear`, `blocked_related_failure`, `warning_unscoped_failures`, `error`; blocking uses explicit `affects` scope only. |
| `check-commit-context.py` | JSON `status`: `ok`, `needs_review`, `unknown`, `error`; reports git-backed recognized range metadata, affected pages/decisions, and handoff requests. |
| `source-claim.py` | JSON `status`: `acquired`, `blocked_overlap`, `released`, `release_denied_wrong_owner`, `not_found`, `clear`, `ok`, `error`; for multi-agent/delegated source edits only. |
| `check-reachability.py` | JSON `status`: `ok`, `warning`, `orphans_found`; broken links are reported as `warning` here and escalated by `validate.py`. |
| `daily-hygiene.py` | JSON `status`: `ok`, `warning`, `critical`, `skipped`, `error`. |
| `record-agent.py` | JSON `status`: `recorded`, `permission_denied`, `error`. |
| `check-hardening.py` | JSON `status`: `ok`, `error`; inspect hardening fields such as `ledger_append_only`, `dangerous_commands_on_path`, and protected-file writability for strength. |
| `generate-docs.py` | Text output only; exit status is the contract. |
| `validate.py` | Text output plus exit status; non-zero means contract failure. |

Mutating scripts may return `permission_denied` when `context/config.json`
does not grant the requested capability.

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
- `kind="module-map"` marks an ordinary context page as a subsystem map. Such
  pages must include `read-when`, `update-when`, and `tracks` or explicit
  `context-only`.

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

`ledger.html` keeps current active locks, current active source claims, and a
bounded recent window from `ledger-events.ndjson`:

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

Source claims are current-state rows in `ledger.html` plus audit events in
`ledger-events.ndjson`. They are used only for multi-agent or delegated source
edits. Exclusive mode is the only V1 mode. No V1 TTL policy is hardcoded. Force
release requires orchestrator or explicit human permission and a ledger event.

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

Bootstrap installs managed context-architecture blocks in target `AGENTS.md` and
`CLAUDE.md`. Those files are the normal roots after setup; `context/index.html`
is only the fallback root when no bootloader file exists.

Root priority:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `.agents/AGENTS.md`
4. `context/index.html`
5. future context-map aliases

The checker inventories live `context/**/*.html`, excluding generated human
docs, then uses BFS over bootloader context references and internal HTML links.
Archived node pages remain reachable through their subsystem archive index.
`tracks`, ledger events, and decision refs are not reachability edges.

Broken internal links are reported as `warning` by `check-reachability.py` and
escalated to validation failure by `validate.py`. Orphans and fallback roots are
warnings in V1.

## Agent Tree

`agent-tree.html` is advisory coordination, not lock authority. It helps agents
see active subagent work before escalating to the orchestrator. Lock/claim
authority remains page lock metas plus the ledger active-lock and active
source-claim tables.

`record-agent.py` upserts one row per `agent-id` and renders a tree from
`parent-id`. Inputs:

`agent-id`, `parent-id`, `role`, `task`, `page`, `scope`,
`expected-actions`, `status`, `details`

Statuses:

- `spawned`
- `active`
- `blocked`
- `handoff`
- `closed`

Lifecycle statuses `spawned`, `blocked`, `handoff`, and `closed` also append a
ledger event. `active` refreshes update only `agent-tree.html`.

## Permissions

Permission profile defaults live in `templates/permission-profiles.json`.
`SKILL.md` frontmatter points to that template. `bootstrap.py` seeds those
defaults into `context/config.json`. Scripts enforce `config.json`; the skill
file itself is only declaration.

Script permissions are workflow enforcement, not an OS sandbox. To prevent an
agent from bypassing scripts, the runtime must deny dangerous commands and/or
protected file writes as described in `context/runtime-policy.md`.

Default roles:

- `orchestrator`: acquire/release locks, break stale locks, force release,
  update tracks, record any agent.
- `worker`: acquire free locks, release own locks, record itself.
- `readonly`: run read-only checks only.

Unknown agents default to `worker` so spawned subagents can self-register and
lock their own page during fan-out. `agentRoles` in `config.json` maps explicit
agent IDs to other roles — pin an ID to `readonly` to deny it, or to
`orchestrator` to grant record-any/break-lock/update-tracks.

## Task Capsules And Receipts

Task capsules are the only model-visible projection of context hygiene. They
contain a one-line task, expected result, canonical scope, role, and only
relevant durable nodes with exact `path#fragment` links. A graph node is eligible
only when its `<meta name="visibility">` is `agent`, `model`, or `public`, its
status is active for its graph kind, and it intersects scope or is named by an
exact task link. Ledger, mutex, receipt, registry, archive, and hygiene mechanics
must not appear in capsule text.

Capsules have hard ceilings of 4,000 characters and eight nodes. Configuration
may lower, never raise, either ceiling. Construction fails closed unless the
context root is canonical. The same root is shared by every Git worktree.

Each capsule appends one `task_capsule` receipt to the canonical ledger. The
receipt records project identity, session/turn, task/result/scope/links, role,
node ids, source-file SHA-256 values, character budget, and a digest over the
record. Restoration requires one uniquely matching ledger record, valid digest
and schema, the same project, canonical scope, and still-relevant nodes; it then
records `restoration_of` lineage. Receipts are audit evidence, never model
context.

## Runtime Lifecycle Hooks

One shared dispatcher normalizes Claude and Codex inputs. Bootstrap merges hooks
by managed identity, preserves unrelated hooks and order, and removes only known
legacy context-architecture entries. Runtime guarantees exist only after hooks
are installed and observed on that runtime; dated observations belong in
`docs/codex-compatibility.md`.

| Event | Contract |
|-------|----------|
| `SessionStart` | No model payload; lifecycle registration only. |
| `UserPromptSubmit` | Inject a capsule only for one unambiguous Firstmate project route. |
| `PreCompact` / `PostCompact` | Pre is inert; Post restores the latest session receipt when one exists. |
| `PreToolUse` | Validate edit paths, ownership, locks, and permission before mutation; malformed or multi-root edits fail closed. |
| `PostToolUse` | Record context reads; run bounded validation/freshness feedback after relevant tools. |
| `SubagentStart` | Inject one bounded capsule when a task is present. |
| `SubagentStop` | Surface validation failure and request at most one continuation per hashed session/agent identity. State is private, mutex-protected, atomic, and mode `0600`. |
| `Stop` / `SessionEnd` | Append a private capture candidate from an explicit final message. `SessionEnd` never reads a transcript path. |

Inline diagnostics are bounded; oversized diagnostics spill to a private file
and expose only its relative path. Hook payloads allowlist known fields and
redact unknown/secret-shaped data.

## Firstmate

Global scope uses the neutral private root
`${XDG_DATA_HOME:-$HOME/.local/share}/context-architecture/firstmate`, overridden
only by `CONTEXT_ARCH_FIRSTMATE`. Git initialization is opt-in. Migration copies
a legacy root into this location and preserves the source.

Firstmate stores an allowlisted project registry, a private capture inbox, and
validation state. Review output is limited to registered names, roots, short
status, and summary. Framework work stays in Firstmate; project work routes only
when a prompt/task matches exactly one registered project name or path. The
resulting capsule is built from that project's canonical context and must not
expose any other registered project.

## Codex Model Role Policy

Semantic roles replace provider-specific names:

| Role | Desired policy | Current direct-surface fallback |
|------|----------------|---------------------------------|
| `lead`, explicit Astra request | `gpt-6-astra` / `high` | same |
| `balanced`, routine work | `gpt-6-sol` / `medium` | same |
| `economy`, bounded delegation | `gpt-6-luna` / `medium` | same |

Policy revision `2026-09-26.1` applies to new bootstrap defaults. Use balanced
for routine implementation/coordination and economy for bounded delegated work.
Selecting lead requires an explicit user request for Astra; it is never an
automatic cost escalation. These selection instructions guide the parent;
profile generation does not intercept arbitrary native spawn calls.
If economy is missing, hidden, or explicitly rejected, catalog resolution may
use visible, supported `gpt-6-sol` / `low`, with a warning and truthful profile.
Missing lead/balanced catalog models fail closed. The direct-surface fallback
for an unknown configured model uses Sol (high/medium/low by role), never Astra.
Explicit supported legacy pins remain intact. Existing project policies are
preserved by refresh unless the catalog advertises a valid upgrade edge; a new
framework default alone does not rewrite them.

Generated `.codex/agents/*.toml` profiles disclose desired and actual values.
Subagents isolate conversation threads, not filesystems; they inherit active
hook composition and parent safety overrides. Parallel writers therefore use
separate Git worktrees sharing the canonical context root.

Only explicit Codex refresh may query `codex app-server --stdio`. It must perform
`initialize`, send `initialized`, consume every `model/list` page, and strictly
validate identities, visibility, efforts, and upgrade metadata. A role changes
only for one unambiguous advertised upgrade target that is present and visible;
unsupported effort uses that target's documented default. Missing, hidden,
conflicting, malformed, timed-out, or unavailable data preserves installed
profiles.

Policy/config/profile files are one compare-and-swap bundle: stage beside each
destination, validate JSON/TOML and required fields, verify baseline digests,
atomically replace, and roll back every partial replacement on failure.

## Source Edit Authorization

Project source may change only when the user supplies both a named target and an
action verb in `fix`, `change`, `edit`, `update`, `modify`, `add`, or `remove`.
Otherwise investigate, report, propose the exact patch, and request approval.
Context HTML is coordination infrastructure and may be updated by its lifecycle.

## Decision Graph

Decision entries are durable rationale, not event history.

`context/decisions.html` is the graph router. Individual decision nodes live
under `context/decisions/`. Archived decision nodes live under
`context/decisions/archived/` and remain reachable through
`context/decisions/archive.html`.

Decision ids use sequential plus slug form, for example
`dec-001-human-docs-projection`. Decision graph edge metadata:

- `builds-on`
- `related`
- `supersedes`
- `resolves`
- `affects`

Backlinks are generated by scripts from outgoing edges; agents edit outgoing
edges only.

Status values:

- `proposed`: not authority.
- `accepted`: authority, may not have code yet.
- `implemented`: authority with code; requires `commits`.
- `superseded`: replaced by a newer decision.
- `deprecated`: retained for rationale, no replacement required.
- `rejected`: explicitly not chosen.

Accepted or implemented decisions must not build on proposed decisions. If a
task depends on a proposed decision, the agent asks the orchestrator/user to
resolve it first.

Legacy decision articles must include `data-status` and these fields:

- `Question`
- `Decision`
- `Rationale`
- `Consequences`
- `Review when`

Optional attributes:

- `data-builds-on`
- `data-tracks`

## Failure Todos

`context/failure-todos.html` is the failure router. Individual failure nodes
live under `context/failure-todos/`. Archived failure nodes live under
`context/failure-todos/archived/` and remain reachable through
`context/failure-todos/archive.html`.

Failure ids use sequential plus slug form, for example
`failure-001-route-diff-broken-glob`.

Blocking is scoped. `affects` controls deterministic blocking; `topics` is for
search and human review only. Unscoped failures are allowed and never block
task completion.

Statuses:

- `open`: unresolved; blocks only when task scope intersects `affects`.
- `authorized`: allowed to proceed; warns when related.
- `blocked`: needs external input/tool/access; blocks related work.
- `resolved`: fixed or no longer reproducible.
- `deprecated`: retained for history; requires rationale.

Repair attempts are counted globally per failure id from ledger events. After
two failed attempts, agents stop speculative patching and report
`needs_orchestrator_trace`.

## Open Questions

`context/open-questions.html` is the question router. Individual question nodes
live under `context/open-questions/`. Answered questions are archived under
`context/open-questions/archived/` and remain reachable through
`context/open-questions/archive.html`.

Question ids use sequential plus slug form, for example
`question-001-routing-staleness`.

Open questions block only when `blocking=true` and current task scope intersects
`affects`, or when current task is listed in `blocked-work`. Durable answers
should become decision nodes; answered question nodes point to `answered-by`.

## Task And Human Question Lifecycle

`context/scripts/task-lifecycle.py` maintains the active-task graph separately
from typed durable workstream nodes. Task nodes use stable `AW-*` IDs beneath
`active-work/`; the `active-work.html` router groups children under `AW-H1` through
`AW-H4`. Dispositioned nodes retain their source paths and are linked from
`active-work/archive.html`. Deferred tasks are removed from the active router;
their questions, contingencies, and activation triggers remain discoverable
through `future-workstreams.html`.

Task states are `untriaged`, `ready`, `in-progress`, `verified`,
`awaiting-captain`, `blocked`, `deferred`, `done`, `accepted`, `rejected`, and
`cancelled`. `ready` reports only ready tasks with no unresolved blocking
questions and with every dependency in `done`, `verified`, or `accepted`.
This is scheduling metadata, not execution authorization or independent
scientific verification.

Lifecycle questions use stable `OQ-*` IDs in `open-questions/`. `new-question`
links the question to its task and records the ask, owner, sources, and
contingency. `blocking` questions block that task; `parked` questions preserve
its current state. `answer-question` removes only that question's blocker and
archives the answer. `defer-question` parks the affected task and records an
explicit activation trigger. `questions` lists unresolved human questions;
owners are configurable through `questionOwners` (defaults: `captain`,
`external`). Existing custom owners are retained on refresh.

All mutating commands take `--actor-id` and require an explicitly configured
actor with `record_self` permission. Read-only `ready` and `questions` need no
write role. All task dispositions require `--actor-id captain --confirm-captain`
and a captain actor configured with the required permission. An `accepted`
disposition additionally requires a `verified` or `awaiting-captain` task.
These actor assertions are workflow checks, not an OS authentication boundary.

Commands serialize against the canonical context root, preflight their affected
pages, use atomic writes, and append audit events. The lifecycle validator checks
IDs, parent heads, dependency and question edges, and terminal routing. Linked
agent-visible lifecycle nodes can enter bounded task capsules using their stable
IDs; completed or deferred tasks are not presented as current work.

Bootstrap and refresh add lifecycle routers and marked question rows without
replacing authored nodes or existing owner lists. The shared hook dispatcher
and platform-specific bootloaders remain authoritative; legacy zip hooks and
automatic context commits are not reinstalled.
Migration that requires editing a locked page waits for that lock to be released.

## Run Intent And Runbooks

`context/run-intent.html` is a router only. It maps execution intent to a
runbook and expected result category. It does not execute commands.

Command details live in `context/runbooks/*.html` as mini skill/how-to pages.
Use one runbook per stable workflow. Split a runbook only when it exceeds page
limits or has multiple distinct workflow lanes.

## Recognized Commits

`context/recognized-commits.html` stores range-first metadata over real git
history. Git is the commit source of truth; context stores only recognized
ranges, heads, short rationale, and links to affected context nodes.

Individual nodes may carry `commits` metadata when a commit directly
implements, updates, resolves, or authorizes that node. Unrecognized commits
produce handoff JSON for orchestrator delegation; scripts do not spawn agents.

## Release Contract

`package.sh <exact-tag>` accepts one filename-safe exact tag and publishes one
transactional version directory: `dist/contarch-<tag>/`. That directory contains
the self-extractor, matching `.tar.gz`, and `.sha256` manifest. The destination
must not already exist and publication must be an atomic, same-filesystem,
no-clobber rename; any failure leaves no partial release and never overwrites an
existing release.

Before verification, packaging requires a clean tracked/untracked status, pins
the current HEAD commit, proves the tag resolves to that exact commit, and finds
the exact tag heading in `CHANGELOG.md`. `scripts/release-verify.sh` is the
canonical executable gate. After it returns, packaging again proves clean
status, unchanged HEAD, and unchanged tag resolution. The payload is always
`git archive <pinned-commit>`, never a mutable tag or working-tree file list.

The verifier runs Python tests, smoke, automated shell tests, Python/shell
syntax, documentation structure, and diff checks. Post-build gates reject
unsafe tar members, mismatched self-extractor payload/version metadata, failed
Claude/Codex/both dry runs, and checksum mismatch. Manual live harness E2E is a
separate explicit release gate.

## Memory Boundary

Ledger events are audit history, not durable semantic memory. Durable knowledge
belongs in wiki pages and decisions. Create a new page only when no existing
page owns the topic, the knowledge is durable, and there is a future read
trigger.

Scripts detect facts. The orchestrator proposes context changes. The user or an
authorized agent approves new pages and destructive cleanup.

## Companion Tools

context-mode is strongly recommended for agents working on this framework or on
repositories bootstrapped by it:

https://github.com/mksglu/context-mode

It handles low-context tool execution, file analysis, indexed retrieval, web/doc
fetch indexing, and session-memory search. It is not contract authority.
Scripts in this repository remain authoritative for `tracks`, routing, locks,
ledger events, agent tree, decisions, reachability/orphan checks, permissions,
and generated `context/` structure.

**Reading-cost contract:** context pages are read body-only via `context/scripts/extract-body.py` (skill-owned, propagated by refresh); raw `cat`/Read of `context/*.html` is discouraged. For all other gathering and file analysis, context-mode (`ctx_batch_execute`, `ctx_execute_file`, `ctx_search`) is the preferred path so raw bytes never enter agent context. extract-body is always present; context-mode is preferred-when-available.
