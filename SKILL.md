---
name: context-architecture
description: "Bootstrap and operate deterministic repo-local context architecture for Codex/Claude-style agent work: map-first context wiki, locks, ledgers, agent tree, decision graph, freshness routing, validation, and low-context multi-agent coordination."
metadata:
  context_architecture:
    contract_version: 1
    default_role: readonly
    permission_profiles: templates/permission-profiles.json
---

Use when:
- The user wants persistent project context, agent memory architecture, or multi-agent coordination
- Starting a new project that needs structured documentation
- An existing project needs a context system bootstrapped
- The user asks for a deterministic context control plane, ledger, locks, decision graph, or context hygiene
- Invoke once per target directory. After bootstrap, generated `AGENTS.md`/`CLAUDE.md` own routine context work.

## Operating Principle

**Scripts own ritual. LLMs own judgment.**

| Script-owned (deterministic) | LLM-owned (judgment) |
|------------------------------|---------------------|
| Lock acquire/release | Is this fact durable? |
| Ledger entry append | What does this decision mean? |
| Diff-to-page routing via `tracks` | Which unmatched fact is durable? |
| Spawn tree entries | Should this page be split? |
| Validation (all invariants) | Is this context still accurate? |
| Staleness detection | Task classification edge cases |
| Doc generation | Summary wording |
| Bootstrap skeleton creation | Content significance |

## Write Discipline

All writes must be surgical. Produce ONLY what was asked. No adjacent cleanup, no "while I'm here" improvements, no unsolicited additions. When an instruction is specific in approach or implementation, the output must contain exactly that and nothing else.

## Workflow

For bundled scripts, set `SKILL_DIR` to the directory containing this `SKILL.md`. In Codex this is normally the active skill folder, for example `~/.codex/skills/context-architecture` when installed locally. If the user says "this repo" and gives no target, use the current working directory as the target.

This is a one-time bootstrap skill for each target directory. Rerun only to repair
or upgrade the installed context architecture.

### Bootstrap (new project)
```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --scan
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project
```
`--scan` is inventory-only and does not write files. Run without `--scan` to generate the full `context/` skeleton and managed `AGENTS.md`/`CLAUDE.md` bootloader blocks after resolving ambiguities.

### Absorb Existing Docs
When a project already has documentation (README, ANALYSIS.md, wiki exports, etc.), `bootstrap.py --scan` reports headed doc import candidates. Import is explicit and small:
```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --absorb-docs
```
This creates headed HTML pages, copies originals under `context/archived/`, and links pages into the index. Do not create pages from chat automatically.

### Task Start
```bash
python3 context/scripts/start-task.py --page <page> --intent "<what you're doing>"
```
Classifies task, checks staleness, acquires lock if needed. Returns: task class + status.

### Route Changed Files
```bash
python3 context/scripts/route-diff.py --files src/parser.py
python3 context/scripts/route-diff.py --from HEAD~1 --to HEAD
```
Matches changed files to page-local `<meta name="tracks">`. Reports matched pages, unmatched files, and stale tracks. No semantic guessing.

### Repair Tracks
```bash
python3 context/scripts/update-tracks.py --page parser.html --add src/parser.py --remove src/old_parser.py
```
Explicit orchestrator repair for stale or missing `tracks` metadata.

### Reachability And Daily Hygiene
```bash
python3 context/scripts/check-reachability.py --json
python3 context/scripts/daily-hygiene.py --json
```
Reachability checks whether live context pages are discoverable from the project bootloader/head page. Daily hygiene is normally hidden: the first non-hygiene ledger event each day runs it automatically and records a `daily_hygiene` event.

### Ledger Hardening
```bash
context/scripts/harden-ledger.sh context
python3 context/scripts/check-hardening.py --json
```
Optional Linux hardening for `context/ledger-events.ndjson`. Run `harden-ledger.sh` as root, an elevated user, or another Unix user that the agent cannot control. If the agent can run `chattr -a`, hardening is advisory only.

### Agent Coordination
```bash
python3 context/scripts/record-agent.py --agent-id worker-1 --parent-id orchestrator --role verifier --task "validate parser" --page parser.html --status spawned --actor-id orchestrator
```
Updates advisory `agent-tree.html`. Use it before asking the orchestrator to release or arbitrate another agent's work. It is not lock authority.

### Task Close
```bash
python3 context/scripts/close-task.py --page <page> --summary "<what changed>"
```
Validates first. If validation passes, releases lock, appends ledger, bumps timestamp, and regenerates docs. If validation fails, keeps the lock for repair.

### Validation (anytime)
```bash
python3 context/scripts/validate.py
```

## Verification (smoke test)

```bash
bash "$SKILL_DIR/smoke.sh"
```

Exercises full lifecycle and contract failures: bootstrap → lock contention → stale lock break → route/freshness → track repair → reachability/hygiene → decision validation → close validation warning → docs. Exit 0 = all pass. Run after any script change.

## Task Classes

- **Read-only**: No locks needed. Just read pages.
- **Tiny write**: ≤5 changed lines, ≤2 files, no structural change. Lock acquired but minimal ceremony.
- **Standard write**: Anything broader. Full lock + ledger + validation cycle.

## Architecture (what gets generated)

```
AGENTS.md                    # Agent bootloader with managed context block
CLAUDE.md                    # Claude bootloader with managed context block
context/
├── index.html              # Map-first retrieval router
├── control-plane.html      # Runtime checklist
├── ledger-events.ndjson    # Append-only event source
├── ledger.html             # Active locks + rendered event view
├── agent-tree.html         # Advisory active agent subtree
├── decisions.html          # Decision graph
├── config.json             # Repo roots, settings, validator config
├── scripts/                # Deterministic tools (copied from skill)
│   ├── start-task.py
│   ├── close-task.py
│   ├── validate.py
│   ├── generate-docs.py
│   ├── check-freshness.py
│   ├── route-diff.py
│   ├── update-tracks.py
│   ├── check-reachability.py
│   ├── check-hardening.py
│   ├── daily-hygiene.py
│   ├── harden-ledger.sh
│   ├── record-agent.py
│   └── context_utils.py
├── hooks/                  # Optional runtime hooks
├── docs/                   # Auto-generated markdown (for humans)
├── archived/               # Copies of absorbed docs
├── runtime-policy.md       # Sandbox/OS hardening guidance
└── [project pages].html    # Domain-specific knowledge pages
```

## Key Design Choices

- HTML source of truth (semantic tags, meta for locks/routing, explicit hrefs)
- Markdown auto-generated for human consumption
- Max 200 lines per page
- Discovery blocks via `<meta name="read-when">`, `<meta name="update-when">`, and page-local `<meta name="tracks">`
- `ledger-events.ndjson` is append-only audit; `ledger.html` is a bounded view; wiki/decision pages hold durable knowledge
- `agent-tree.html` is advisory coordination; locks remain page metas plus ledger active locks
- Permission profile defaults live in `templates/permission-profiles.json`; skill frontmatter points to that template, bootstrap seeds config, and scripts enforce generated `context/config.json`
- New page only when no existing page owns topic, knowledge is durable, and a future read trigger exists
- Decisions form a graph (`data-builds-on`, required rationale fields, optional `data-tracks`)
- Lock arbitration: subagents self-manage, orchestrator arbitrates contention
- Hooks are optional/advisory unless installed and verified in the active runtime
