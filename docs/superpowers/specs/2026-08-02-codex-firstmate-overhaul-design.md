# Codex and Firstmate Overhaul Design

**Status:** Approved design, pending implementation plan

**Date:** 2026-08-02

**Baseline:** `openai/codex` stable `0.146.0`; prereleases are watch-only

## Goal

Import the `contarch-15d5dd0` upgrade into the tracked context-architecture
repository, preserve its Claude Code behavior, and make Codex a first-class
harness. Firstmate, context locking, routing, validation, capture, model roles,
documentation, packaging, and release checks must work from one shared source.

## Inputs and Provenance

- Tracked repository: `/data/vishn/context-architecture`, baseline commit
  `143f826`.
- Upgrade artifacts: `contarch-15d5dd0.tar.gz` and its byte-equivalent
  self-extracting `contarch-15d5dd0.sh` payload.
- Archive safety audit: 72 regular files; no absolute paths, path traversal,
  links, or device entries.
- Archive verification: 90 smoke assertions, 37 Python tests, six automated
  shell tests, syntax checks, package rebuild, and installer dry runs passed.
- Existing repository verification: 89 smoke assertions passed before changes.

The archive is imported as a provenance commit before adaptation. Existing
repository metadata, `README.md`, `LICENSE`, `AGENTS.md`, and authored documents
remain authoritative where the archive does not intentionally replace them.

## Chosen Architecture

Use one shared deterministic core with thin Claude and Codex adapters. Do not
fork the project by harness and do not introduce a plugin framework.

The shared core continues to own:

- context pages, locks, ledgers, decisions, failures, routing, and freshness;
- task start/close and validation workflows;
- Firstmate registry, capture inbox, review, and project discovery;
- Git pre-commit and post-commit behavior;
- model-neutral task roles;
- four concise typed knowledge graphs;
- packaging and release verification.

Harness adapters own only:

- platform detection and explicit platform selection;
- bootloader wording and managed instruction blocks;
- hook configuration, event matchers, payload normalization, and responses;
- custom-agent/profile generation;
- user-global installation paths.

Two harnesses justify this seam. They do not justify a class hierarchy. A small
stdlib Python module and a single hook dispatcher are sufficient.

## Four Typed Knowledge Graphs

The context wiki becomes four typed graphs over the existing shared page, lock,
ledger, track-routing, reachability, and agent-orchestration machinery:

| Graph | Durable content | Router | Node directory |
| --- | --- | --- | --- |
| Wiki | Current facts, architecture, interfaces, operating knowledge | `wiki.html` | existing project pages; `wiki/` for new nodes |
| Decisions | Options, rationale, selected direction, supersession | `decisions.html` | `decisions/` |
| Failures | Failed attempts, symptoms, causes, recovery, prevention | `failure-todos.html` displayed as Failures | `failure-todos/` |
| Workstreams | Open/future work, dependencies, blockers, completed history | `workstreams.html` | `workstreams/` |

These are four graph families, not four engines. Existing mutex, page-lock,
ledger, source-claim, agent-tree, reachability, and archive code remains common.
A small shared `knowledge_graph.py` module of plain stdlib functions parses the
four families and handles IDs, statuses, links, head rules, archives, and
reachability. Family-specific validation remains local because a decision
rationale, failure authorization, wiki fact, and work item do not share the same
semantics. Existing parsers are reused and moved into the shared module only as
their callers are touched.

### Router and Head Invariant

Each main graph page is a router. Its graph section contains only live HEAD
nodes. A HEAD is a live node with no parent in that graph. It may link to child
nodes, related nodes, source files, or external detail; it simply cannot be
placed beneath another live node. This map-first, concise exploration behavior
is the default, not an optional verbosity mode.

Router pages never become exhaustive lists or prose dumps. Navigation to an
archive is allowed outside the graph section. Child nodes are discovered by
following explicit parent-to-child links. Every child links back to its parent.
The validator rejects:

- a non-HEAD node placed on a router;
- a live HEAD omitted from its router;
- a child linked by only one side of the relationship;
- a missing, cross-family-invalid, or archived live parent;
- cycles in parent relationships;
- any live node unreachable from `index.html` by breadth-first link traversal.

`index.html` links the four routers. Existing reachability and track-routing
checks continue to require every live context file to be discoverable and every
relevant source path to be owned by a page or explicitly ignored.

### Concise Node Contract

Each node contains only what changes future work. Required structure is limited
to identity, lifecycle state, a one-paragraph durable statement, and graph
links. Detail already owned by another context page, source file, commit, issue,
or report is linked, not copied.

Common structural fields are:

- stable ID;
- status;
- optional parent reference, absent only for a HEAD;
- explicit child and related links;
- optional source ownership or `affects` links when routing needs them.

The directory determines graph type and the heading supplies the title, so those
values are not duplicated in metadata. Optional fields exist only when their
family semantics require them.

Family content stays minimal:

- Wiki: durable fact plus its evidence/owned files; status `active`,
  `superseded`, or `deprecated`. Freshness remains computed from tracks and
  review timestamps rather than being duplicated as an authored status.
- Decision: choice and reason; existing decision statuses and semantic edges
  (`builds-on`, `related`, `supersedes`, `resolves`, `affects`) remain valid.
- Failure: symptom, cause when known, recovery/prevention link, and resolver;
  status `open`, `authorized`, `blocked`, `resolved`, or `deprecated`.
- Workstream: desired outcome and next action; status `backlog`, `active`,
  `blocked`, `done`, or `cancelled`, with optional `depends-on`, `part-of`, and
  `blocked-by`. `work-kind` distinguishes a stream, task, or unresolved question
  without creating another graph.

Routine task close is blocked only by an applicable open failure. Workstreams
route and warn; they do not block unrelated completion merely because future
work exists.

### Head Consolidation

Many unrelated HEADs are valid initially. As the graph grows, several HEADs may
reveal a shared parent concept. Daily hygiene reports consolidation candidates
when three or more live HEADs share the same normalized `affects` target, source
ownership prefix, or explicit topic. The script never rewrites authored graphs.
An agent reviews the candidate, creates the smallest meaningful parent HEAD, and
reparents the former HEADs as children when that improves exploration.

This is an information-architecture judgment, not a clustering system. No
embeddings, similarity service, or automatic title-based grouping is added.

### History and Migration

Resolved failures, superseded decisions, deprecated wiki facts, and completed or
cancelled workstreams move to each family's `archived/` directory. Archive
indexes remain reachable through navigation but never appear as live HEADs.
Links from live nodes to historical evidence remain valid.

`history.html` is a generated chronological view across all four graphs, not a
fifth graph. It links completed/cancelled work, resolved/deprecated failures,
superseded/rejected decisions, and superseded/deprecated wiki knowledge.

Current generic project pages become Wiki nodes in place only when they already
represent durable knowledge. Existing `decisions/` and `failure-todos/` content
keeps its paths, IDs, and edges. `open-questions/` remains readable in place and
normalizes as Workstream nodes with `work-kind="question"`; new actionable work
uses `workstreams/`. No bulk rewrite, path move, or migration script is added.
New or touched nodes use the current contract; untouched legacy nodes continue
through compatibility parsing. Refresh never deletes legacy source files.

## Platform Selection

Bootstrap accepts `--platform claude`, `--platform codex`, or `--platform both`.
Explicit selection always wins. Environment detection may supply a default only
when it is unambiguous. The existence of both `~/.claude` and `~/.codex` is not
evidence that Claude should win; an ambiguous non-interactive invocation fails
with an actionable message.

`--refresh` preserves the platform choice stored in project configuration. It
does not redetect and switch harnesses.

## Harness Instruction Files

Common policy is authored once and rendered into platform-specific managed
blocks:

- Codex: `AGENTS.md` and optional `.codex/agents/*.toml`.
- Claude Code: `CLAUDE.md` and `.claude/settings.json`.

Managed marker blocks preserve all user-authored content outside the markers.
Claude-specific tool names and slash commands never appear in the Codex block;
Codex-specific collaboration or `ctx_*` names never appear in the Claude block.

The main skill stays concise. Detailed platform contracts live in documentation
and are loaded through progressive disclosure.

## Hook Adapter

A single stdlib dispatcher receives an event name and JSON on standard input,
normalizes the payload, calls existing shared behavior, and renders the correct
harness response. This prevents lifecycle behavior from being duplicated across
many shallow scripts.

The canonical input contains:

- event kind, current directory, session ID, turn ID, and optional agent ID;
- tool name and raw tool input;
- every affected path extracted from an edit or patch;
- active model and permission mode when supplied;
- prompt or final message when supplied by the event.

The canonical result contains:

- allow or block plus an actionable reason;
- additional developer context;
- optional normalized tool input;
- optional child-continuation request.

Codex behavior follows its released schema:

- `apply_patch` patch text is read from `tool_input.command` and may name
  multiple files.
- `PreToolUse` blocks with `permissionDecision: "deny"`; `continue: false` is
  not used as a blocking mechanism.
- Matching hooks may run concurrently, so no event depends on another matching
  hook completing first.
- `SubagentStart` injects project context but does not attempt to block spawn.
- `SubagentStop` emits valid JSON and requests continuation only for a concrete,
  bounded validation failure.
- Transcript files are diagnostic inputs only; their format is not parsed as a
  stable API.
- Hosted tools that bypass local hooks remain governed by `AGENTS.md` policy and
  explicit validation, not a false claim of universal hook enforcement.

Hook installation merges a named managed group into existing user, project, and
plugin hook configuration. It never overwrites unrelated hooks. Project hooks
are documented as trust-gated.

## Firstmate

Firstmate remains a cross-project coordination layer, not a Claude-only mode.
Its default data root becomes:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/context-architecture/firstmate
```

`CONTEXT_ARCH_FIRSTMATE` overrides this path. `FIRSTMATE_HOME` remains a
deprecated compatibility alias during migration. Existing Claude data is copied
only by an explicit migration command; no source directory is deleted.

Global bootstrap creates the registry, capture inbox, configuration, and
validation state. It does not initialize a Git repository unless `--init-git`
is explicitly passed. When Git automation is unavailable, bootstrap reports
that fact instead of silently skipping it.

Firstmate lifecycle on Codex:

| Behavior | Mechanism |
| --- | --- |
| Thin startup briefing | `SessionStart` |
| Prompt-time routing reminder | `UserPromptSubmit`, only when relevant |
| Project-aware child briefing | `SubagentStart` |
| Child validation | `SubagentStop` |
| Context preservation | `PreCompact` and `PostCompact` |
| Edit gate | `PreToolUse` |
| Staleness/validation update | `PostToolUse` and Git hooks |
| Capture inbox entry | `Stop` or `SessionEnd` |

Registry generation owns a marker-delimited section. Project bootstrap updates
that section deterministically; users do not paste generated HTML manually.
Authored registry content outside the section survives refresh.

## Model Policy

Permissions and task roles remain separate. The policy uses semantic roles:

| Role | Claude default | Codex default | Effort |
| --- | --- | --- | --- |
| `lead` | Opus | `gpt-5.6-sol` | `high` |
| `balanced` | Sonnet | `gpt-5.6-terra` | `medium` |
| `economy` | Haiku | `gpt-5.6-luna` | `medium` |

`lead` covers Firstmate orchestration, architecture, difficult diagnosis, and
final review. `balanced` covers implementation, context authorship, and normal
verification. `economy` covers narrow collection, inventory, and repeatable
read-only work.

The policy is stored once with a revision and rendered into platform agent
profiles. Model availability is checked against Codex's native
`app-server model/list` response. An adapter must not claim a requested model
was used when a particular spawn surface rejects it. For an unavailable economy
model, the invocation warns and uses Terra at low effort; the recorded outcome
names the actual model.

## Model Refresh

Normal sessions never rewrite model policy. Deliberate `--refresh` performs a
catalog check:

1. Query `codex app-server --stdio` with `model/list`.
2. Confirm each configured model is available and supports its configured
   effort.
3. Apply a replacement only when Codex supplies an explicit non-null upgrade
   target and that target is locally available.
4. Ignore prerelease release notes and model-name guesses.
5. Preserve the current value and warn when the catalog is unavailable,
   malformed, or ambiguous.
6. Report every generated-profile change.

Checked-in defaults change only in a normal tagged context-architecture release
with a changelog entry and updated fixtures. Local generated profiles may follow
Codex's explicit upgrade metadata during refresh without dirtying the source
repository.

## Subagent Isolation and Coordination

Codex subagents provide conversation-thread isolation, not filesystem
isolation. They share the parent working directory and may conflict when editing
the same checkout.

Defaults:

- collection and inventory: self-contained prompt, minimal history, read-only
  sandbox, economy model;
- implementation: bounded relevant history, workspace-write sandbox, balanced
  model;
- orchestration and final review: enough history for decisions and constraints,
  lead model;
- parallel writers: separate Git worktrees;
- shared context directory: context-page locks and ledgers remain mandatory.

The current runner's `fork_turns` control is used when exposed, but it is not a
portable contract. `none` still retains system, project, hook, and instruction
context. The adapter discovers available collaboration tools and context controls
at runtime and otherwise emits self-contained task prompts.

Subagents inherit the active hook composition and parent sandbox/permission
overrides. Custom Codex agents may further constrain sandbox, MCP servers,
skills, model, and reasoning effort. Parent live safety overrides take
precedence.

## Refresh and Migration

Refresh updates generated machinery while preserving:

- authored context pages and external instruction text;
- registry and capture inbox history;
- project configuration and accepted model-policy revision;
- unrelated user, project, and plugin hooks;
- Git history and repository metadata.

Refresh validates after writing and returns nonzero on a broken installation.
Migration is recoverable: existing files are backed up before managed blocks or
generated files change, and legacy Firstmate data remains in place.

## Documentation and Compatibility Tracking

The repository maintains three non-duplicative views:

- `README.md`: quickstarts and a compact feature/capability matrix.
- `CHANGELOG.md`: `Unreleased` plus tagged user-visible changes. No invented
  history.
- `docs/codex-compatibility.md`: verified stable CLI version/date, hook events,
  custom-agent/model behavior, live probes, known gaps, and an upstream
  watchlist.

`docs/contracts.md` remains the behavioral source of truth. The compatibility
document records only Codex changes that can affect this project; it does not
mirror OpenAI's release notes.

## Release and Packaging

Release packaging accepts an exact tag and enforces:

1. clean Git status, including untracked files;
2. tag resolves exactly to `HEAD`;
3. matching `CHANGELOG.md` entry;
4. full shared and adapter verification;
5. payload creation with `git archive <tag>`;
6. SHA-256 checksums;
7. byte equality between the standalone tarball and self-extractor payload;
8. installer dry runs for Claude-only, Codex-only, and dual installation.

The existing `git describe --dirty` plus `git ls-files -co` package path is
removed because untracked content can be shipped under a misleading version.

## Testing

All behavior changes use red-green TDD. The smallest useful layers are:

- shared unit tests for platform selection, payload normalization, affected-path
  extraction, model catalog upgrades, Firstmate path migration, typed-node
  parsing, and HEAD classification;
- graph-family tests proving router purity, bidirectional parent/child links,
  cycle rejection, archive isolation, BFS discovery, concise required fields,
  normalized legacy paths, generated history, and deterministic
  head-consolidation suggestions;
- adapter tests proving generated Claude and Codex configuration contains no
  cross-platform vocabulary and preserves authored content;
- lifecycle tests for refresh, global/project Firstmate bootstrap, registry
  updates, and Git availability reporting;
- fixture tests pinned to the Codex 0.146 hook and model-list schemas;
- portable, opt-in live Codex probe covering SessionStart, SubagentStart,
  child Pre/PostToolUse, SubagentStop, and generated profile selection;
- portable, environment-gated Claude end-to-end tests;
- existing ledger, mutex, routing, permission, freshness, validation, and Git
  hook regressions;
- release package and installer verification.

Live probes never modify global configuration. They use temporary repositories,
sanitized logs, bounded execution, and cleanup checks.

## Error Handling

- Ambiguous platform: fail before writing.
- Existing malformed hook configuration: fail with path and parse error; keep
  original bytes.
- Partial managed-block write: write temporary file and atomically replace.
- Missing model catalog: retain profiles and warn.
- Unsupported model/effort: use the documented role fallback and record the
  actual selection.
- Lock contention: bounded wait, heartbeat/PID recovery, then deterministic
  contention intent; never steal a live lock.
- Failed validation after refresh: return nonzero and identify the generated
  files involved; backups remain available.
- Missing Git for optional Firstmate automation: report reduced capability,
  without silently initializing a repository.
- Invalid graph edit: keep the page lock, report the exact broken edge or router
  invariant, and do not regenerate projections.

## Explicit Non-Goals

- No automatic GitHub pull requests or scheduled release bot.
- No background daemon watching OpenAI releases.
- No plugin marketplace packaging in this iteration.
- No promise that hooks cover hosted tools.
- No silent prerelease adoption.
- No filesystem isolation without a worktree or separate checkout.
- No rewrite of the deterministic context-page core.
- No database, graph service, embeddings, or duplicated per-family lock engine.

These can be added only after a measured need or a stable native Codex feature
makes them smaller than the current solution.

## Acceptance Criteria

- Archive capabilities are present or explicitly superseded with a documented
  migration.
- Claude tests retain parity.
- Codex project and global bootstrap install working managed configuration
  without overwriting unrelated hooks or instructions.
- Live Codex child tool calls trigger the expected project hooks.
- Firstmate operates from the neutral data root and refresh preserves authored
  state.
- Wiki, Decisions, Failures, and Workstreams use the common mutex, ledger,
  reachability, and agent orchestration paths.
- Each graph router contains every live HEAD and no child nodes; every live node
  is reachable from `index.html`.
- Nodes stay concise and link to existing detail instead of copying it.
- `history.html` exposes terminal historical nodes without becoming another
  authored graph or polluting live routers.
- Hygiene reports deterministic consolidation candidates without rewriting the
  authored graph.
- Role profiles select Sol, Terra, and Luna where supported and disclose any
  fallback.
- Explicit Codex model upgrade metadata updates generated profiles during
  deliberate refresh.
- README feature matrix, changelog, compatibility document, and release checks
  agree.
- Full verification passes from a clean tagged-tree simulation.
