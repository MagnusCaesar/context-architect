---
name: context-architecture
description: "Bootstrap and operate deterministic repo-local context architecture for Codex/Claude-style agent work: map-first context wiki, locks, ledgers, agent tree, decision graph, freshness routing, validation, and low-context multi-agent coordination."
metadata:
  context_architecture:
    contract_version: 1
    default_role: worker
    permission_profiles: templates/permission-profiles.json
---

Use when:
- The user wants persistent project context, agent memory architecture, or multi-agent coordination
- Starting a new project that needs structured documentation
- An existing project needs a context system bootstrapped
- The user asks for a deterministic context control plane, ledger, locks, decision graph, or context hygiene
- Invoke once per target directory. After bootstrap, generated `AGENTS.md`/`CLAUDE.md` own routine context work.

## Intent & Objectives

**North star: deterministic context management that is invisible to the agent.** The agent should
not have to know context management is happening — hooks manage most of it automatically. Determinism
is the point: a mechanism only counts if it happens regardless of what the agent knows, forgets, or
routes around.

**Why the decision graph exists.** As development proceeds, decisions get made about the project and
recorded in context. During later development we must not replace or redo something that was done for
a reason we since forgot — so before making a new choice, the relevant decisions are read first. In
autonomous development, old decisions are a *source* and new decisions are *added* as work proceeds.

- `decisions.html` is a **router**, not a listing. It carries only HEAD decisions — the base grounds
  of truth from which the related decision *tree* is explored. A head is an entry point into a tree,
  not a single decision. The goal is to explore the needed context and then find the relevant
  decisions, not to dump every decision on one page. Child nodes are reached via parent links.

**One shared common context.** There is a single shared context — one copy. This is the entire reason
the architecture exists: to prevent multiple divergent decision directions. Decisions and failures are
updated sequentially against that one copy.

**Parallel writes target context, not code.** Code isolation is handled by git worktrees, so code is
not a contention concern. Contention is concentrated in context: e.g. ~5 subagents implementing ~5
features on separate worktrees finish at different times but all update the *same shared* context with
what they did and why. The architecture must serialize those writes deterministically.

**Hooks are skill-owned.** The hooks live in this skill and are applied to all repos from here (via
`scripts/bootstrap.py`). Fixes go in the skill and propagate on refresh — repos do not carry
independent hook logic.

> Constraint that shapes every trim: **not all hooks reach subagents.** On Claude Code 2.1.201,
> PreToolUse/PostToolUse do **not** fire for subagent tool calls — only SubagentStart and SubagentStop
> do. Any guarantee that must hold for parallel subagents has to live at those two points, or it is
> honor-system. See `## Known Failure Modes`.

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

## Reading Discipline

Reads must be cheap. Context pages (`context/*.html`) are read body-only via `python3 context/scripts/extract-body.py <page.html> ...` — never raw `cat`/Read (that burns tokens on lock/infra meta). For all other gathering and file analysis, prefer `/context-mode:context-mode` (`ctx_batch_execute`, `ctx_execute_file`, `ctx_search`) so raw bytes stay out of context. extract-body is always present; context-mode is preferred-when-available.

## Workflow

For bundled scripts, set `SKILL_DIR` to the directory containing this `SKILL.md`. The skill auto-detects the platform at runtime:
- **Claude Code**: `~/.claude/skills/context-architecture` — auto-installs hooks via `.claude/settings.json` (stdin JSON wrappers)
- **Codex**: `~/.codex/skills/context-architecture` — hooks copied to `context/hooks/` only; agents read install comments in each script

If the user says "this repo" and gives no target, use the current working directory as the target.

This is a one-time bootstrap skill for each target directory. Rerun with `--refresh`
to upgrade the installed machinery (see below).

### Bootstrap (new project)
```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --scan
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project
```
`--scan` is inventory-only and does not write files. Run without `--scan` to generate the full `context/` skeleton, managed `AGENTS.md`/`CLAUDE.md` bootloader blocks, and install the **context gate hooks** into project-level `.claude/settings.json` after resolving ambiguities.

### Global first-mate scope (fresh target only)

When the target has **no** `context/` yet, ask the captain which scope to set up
(bootstrap is non-interactive, so the *agent* asks, then passes the flag):

> No context found here. Set up: **[1] project** context (default) or
> **[2] global** first-mate context?

- **[1] / default:** proceed exactly as the Bootstrap block above
  (`bootstrap.py --target <dir>`). Nothing changes.
- **[2] global:** this becomes the cross-project first-mate instance. Run:
  ```bash
  mkdir -p ~/.claude/firstmate && \
  python3 "$SKILL_DIR/scripts/bootstrap.py" --target ~/.claude/firstmate --scope global
  ```
  Then seed the project registry by walking your projects (run directly, or
  dispatch one `model: haiku` subagent so the raw walk output stays out of context):
  ```bash
  python3 ~/.claude/firstmate/context/scripts/seed-registry.py \
      --roots ~/projects --max-depth 4 >> /tmp/fm-registry.txt
  ```
  Paste the resulting lines into `~/.claude/firstmate/context/project-registry.html`
  as `<article class="project">name | path | one-liner | status</article>` rows.

Re-running `--scope global` later is safe (idempotent hooks/scripts refresh); re-run
`seed-registry.py` to pick up new projects and flag dead paths.

**Routing note:** requests about the context-architecture framework itself
(bootstrapping, hooks, the registry, this skill) are the first-mate's own domain —
route them to `~/.claude/firstmate/context/`, not into any individual project.

### Refresh (existing project — idempotent upgrade)
```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --refresh
```
Run this on a directory that **already has `context/`** to pull in newer skill machinery without disturbing authored content. Idempotent — running it twice changes nothing the second time.

**Updates (skill-owned, overwritten):** all `context/scripts/*.py` + `*.sh`, `context/hooks/*.sh`, the git `post-commit` hook, `runtime-policy.md`, `.gitignore` (`.locks/` entry), and the `hooks` block in `.claude/settings.json`. Also **adds any missing self-healing config keys** (`autoAcquireOnEdit`, `autoReleaseOnCommit`, `autoReleaseIdleMinutes`, `contentionBreakMinutes`, `staleLockMinutes`) via merge.

**Preserves (authored, never touched):** `index.html`, `decisions/`, `failure-todos/`, `open-questions/`, ledger, and all **existing** config values (only missing keys are added).

After refresh it runs `validate.py` and reports failures. New failures usually mean the project's pages predate stricter checks added to the skill (e.g. `router_structure`, `required_meta`, `decision_edges`) — treat them as a **migration backlog**, not a refresh error. Safe to run against a live session: machinery files are stateless (re-read per invocation); locks/heartbeats/ledger are untouched.

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

### Subagent Spawning

**Default to parallel execution.** When a task decomposes into independent subtasks that don't contend on the same page lock, spawn a subagent for each. Serial execution of parallelizable work is a waste — the ledger and agent-tree exist precisely to make concurrent work safe.

**Decision rule:** If two subtasks target different pages (different locks), they MUST run as parallel subagents. If they target the same page, serialize or have one agent handle both. When uncertain, check `context/agent-tree.html` for active locks and spawn accordingly.

**No limits on scale or depth:**
- Spawn as many subagents as the task requires — no cap on count or nesting
- Workers can spawn their own sub-workers (nested fan-out)
- Each level inherits the coordination protocol: register → lock → work → close

**Protocol:**
- Every spawned agent MUST register via `record-agent.py` before doing work
- Each agent acquires its own page locks — no sharing locks across agents
- The orchestrator arbitrates contention; any agent at any depth can escalate
- Agents read the full agent-tree to see who else is active before spawning more

**Model selection (cost control):** when spawning via the Agent/Task tool, pick the model by what the subagent does:
- **Collection/explore/read-only** (raw walk, grep, gather-info, `--role` other than implementer/verifier writing context) → `model: haiku`
- **Writes to `context/*.html`** (implementer/verifier roles that author decisions, ledger entries, or page content) → `model: sonnet`

**Pattern — nested fan-out:**
```bash
# Orchestrator decomposes work, spawns parallel workers
python3 context/scripts/record-agent.py --agent-id worker-1 --parent-id orchestrator --role implementer --task "build parser" --page parser.html --status spawned --actor-id orchestrator
python3 context/scripts/record-agent.py --agent-id worker-2 --parent-id orchestrator --role implementer --task "build dashboard" --page dashboard.html --status spawned --actor-id orchestrator

# worker-1 further decomposes its own work
python3 context/scripts/record-agent.py --agent-id worker-1a --parent-id worker-1 --role implementer --task "handle setup paths" --page reproducibility.html --status spawned --actor-id worker-1
python3 context/scripts/record-agent.py --agent-id worker-1b --parent-id worker-1 --role tester --task "test parser output" --page parser.html --status spawned --actor-id worker-1
```

**Lifecycle:** `spawned` → `active` → `closed` (or `blocked` → escalate → `active`). Closed agents are retained in the tree for audit until hygiene prunes them.

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
├── ledger.html             # Active locks/source claims + rendered event view
├── agent-tree.html         # Advisory active agent subtree
├── decisions.html          # Decision graph router
├── decisions/              # One-file-per-decision nodes + archive
├── failure-todos.html      # Scoped failure router
├── failure-todos/          # One-file-per-failure nodes + archive
├── open-questions.html     # Unresolved question router
├── open-questions/         # One-file-per-question nodes + archive
├── recognized-commits.html # Git range/context sync metadata
├── reproducibility.html    # Setup/env/path facts
├── run-intent.html         # Intent-to-runbook router
├── runbooks/               # Mini skill/how-to command pages
├── config.json             # Repo roots, settings, validator config
├── scripts/                # Deterministic tools (copied from skill)
│   ├── start-task.py
│   ├── close-task.py
│   ├── validate.py
│   ├── generate-docs.py
│   ├── find-tracking-page.py
│   ├── auto-release-on-commit.py
│   ├── check-freshness.py
│   ├── route-diff.py
│   ├── update-tracks.py
│   ├── check-failure-todos.py
│   ├── check-commit-context.py
│   ├── source-claim.py
│   ├── check-reachability.py
│   ├── check-hardening.py
│   ├── daily-hygiene.py
│   ├── harden-ledger.sh
│   ├── record-agent.py
│   └── context_utils.py
├── hooks/                  # Self-healing hooks (installed by bootstrap)
│   ├── pre-edit-context-inject.sh
│   ├── post-edit-validate-and-stale.sh
│   └── remind-capture-decision.sh
├── .git/hooks/
│   └── post-commit         # Auto-release on commit
├── .locks/                 # Sentinels (gitignored, ephemeral)
│   ├── hb-{agent_id}      # Heartbeat files
│   ├── pid-{page}         # PID sentinels
│   └── intents.ndjson     # Intent registry
├── archived/               # Copies of absorbed docs
├── runtime-policy.md       # Sandbox/OS hardening guidance
└── [project pages].html    # Domain-specific knowledge pages
docs/
└── context/                # Human-facing projection generated from context
```

## Self-Healing Architecture (Zero Explicit Steps)

Bootstrap installs a self-healing hook system. Agents never run `start-task`, `close-task`, or read context manually. The infrastructure delivers what the agent needs and handles lifecycle automatically.

**Agent experience: 0 procedural steps.** Just edit. Everything else is invisible.

### What Fires Automatically

| Trigger | What Happens |
|---------|--------------|
| Any Edit/Write | PreToolUse: heartbeat touch, context injection, auto-lock (context pages), stale reap, contention surfacing |
| Any Edit/Write | PostToolUse: validation warning, line count check, staleness alert for impl pages |
| Git commit in `context/` | post-commit hook: release locks for committed pages, run validation, regen docs |
| Idle 24h (sanity) | Stale lock reaper releases on next edit |
| Subagent dies | Heartbeat goes stale (>3 min), next contending agent breaks the lock immediately |
| Session crashes | PID sentinel goes dead, reaper releases immediately |

### Lock Lifecycle (Invisible to Agent)

```
Edit context page → hook auto-acquires lock (agent sees "[auto-lock] Acquired")
Edit again → hook sees lock owned by same agent → pass through
Commit → post-commit releases lock + clears intents + runs validation
```

### Contention Resolution

```
Agent-2 blocked on page X (held by Agent-1):
  1. Check Agent-1 heartbeat (mtime of .locks/hb-{agent})
  2. Stale > contentionBreakMinutes (3 min)? → Fast-break, give to Agent-2
  3. Fresh? → Write blocked intent to .locks/intents.ndjson
  4. Orchestrator sees on next edit: "[contention] agent-2 wants X: <intent>"
  5. Orchestrator decides: wait/kill/split based on intent comparison
```

### Context Injection (Source Files)

On every source file edit, the hook injects via stderr:
- **Tracking pages** (context pages with `<meta name="tracks">` matching the file)
- **Active decisions** (decisions mentioning the file + full ancestor chain via builds-on)
- **Open failure-todos** affecting the file

Decision tree traversal walks `builds-on` edges upward to show the full constraint ancestry.

### Hooks Installed

**settings.json entry** (project-level):
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "bash context/hooks/remind-capture-decision.sh" }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "bash context/hooks/pre-edit-context-inject.sh" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "bash context/hooks/post-edit-validate-and-stale.sh" }
        ]
      }
    ]
  }
}
```

`remind-capture-decision.sh` (UserPromptSubmit) scans each user message for decision/failure/open-question language and emits a one-line nudge to capture it. It never writes — the LLM owns the judgment of whether to record.

**Git hook** (installed into `context/.git/hooks/post-commit`):
- Auto-releases locks for committed pages
- Runs validation + doc regeneration
- Always exits 0 (never blocks commit)

### Config Fields

- `testCmd` (optional, default `""`): a shell command to run the project's tests. When non-empty, the git pre-commit runs it and blocks the commit on failure (named failing tests + tail printed; bypass a flaky/unrelated failure with `git commit --no-verify`). Empty = gate disabled. Resolved from the config next to `context/` (a split code/context layout will not auto-run it).

```json
{
  "autoAcquireOnEdit": true,
  "autoReleaseOnCommit": true,
  "autoReleaseIdleMinutes": 1440,
  "contentionBreakMinutes": 3
}
```

### Intent Registry (.locks/intents.ndjson)

Written automatically on lock acquire and contention block. Orchestrator reads pending contentions on every edit. Resolution strategies:
- **Orthogonal intents**: queue blocked agent, grant on release
- **Overlapping intents**: kill lower-priority agent, merge findings
- **Identical intents**: kill duplicate, credit original

### Files Added to context/scripts/

| File | Purpose |
|------|---------|
| `find-tracking-page.py` | Reverse-index: file path → relevant context (tracking pages + decisions + failure-todos) |
| `auto-release-on-commit.py` | Post-commit: release locks, validate, regen docs |

### Sentinel Files (.locks/, gitignored)

| File | Purpose |
|------|---------|
| `hb-{agent_id}` | Heartbeat (mtime = last edit by this agent) |
| `pid-{page}` | PID of process that acquired lock (session crash detection) |
| `intents.ndjson` | Intent registry for contention resolution |

This ensures:
- Agents cannot edit context pages without locks (auto-acquired, invisible)
- Agents see relevant constraints before editing source files (injected via stderr)
- Dead agents don't hold locks forever (heartbeat + PID + 24h sanity)
- Contention is surfaced to orchestrator with both agents' intents for resolution
- Agents cannot forget to update context — `remind-context-update` fires after every project source edit, prompting `route-diff` and page updates
- Validation runs automatically — `post-edit-validate-wrapper` catches broken links/line limits immediately

## Project Edit Policy

Uses a **whitelist decision procedure** — agents run an explicit 4-step test before touching source files:

1. Extract the ACTION VERB from the user's message.
2. Check: is that verb in {fix, change, edit, update, modify, add, remove}? "Handle", "deal with", "clean up", "sort out" are explicitly NOT qualifying.
3. Check: does the message name a specific TARGET (file, function, behavior)?
4. BOTH verb qualifies AND target named → edit permitted (that target only). ANYTHING ELSE → investigate, report findings with line numbers, propose fix as code block, ask "Would you like me to apply this?"

The test result is final. Bug severity, fix obviousness, detailed descriptions, or "it's clearly what they want" do NOT upgrade a NO. The agent must show its work (name the verb, check the set).

Context pages (`context/*.html`) may be updated freely — they are coordination infrastructure, not deliverables.

## Key Design Choices

- HTML source of truth (semantic tags, meta for locks/routing, explicit hrefs)
- Human docs under `docs/context/` are generated projections from context
- Max 200 lines per page
- Discovery blocks via `<meta name="read-when">`, `<meta name="update-when">`, and page-local `<meta name="tracks">`
- `ledger-events.ndjson` is append-only audit; `ledger.html` is a bounded active-lock/source-claim view; wiki/decision pages hold durable knowledge
- `agent-tree.html` is advisory coordination; locks remain page metas plus ledger active locks
- Source claims are ledger-backed coordination for multi-agent/delegated source edits only
- Permission profile defaults live in `templates/permission-profiles.json`; skill frontmatter points to that template, bootstrap seeds config, and scripts enforce generated `context/config.json`
- New page only when no existing page owns topic, knowledge is durable, and a future read trigger exists
- Decisions form a graph (`builds-on`, `related`, `supersedes`, `resolves`, `affects`)
- **Decision-Graph Convention (enforced by validate.py):**
  1. `decisions.html` holds HEAD-node `<article class="decision">` elements inline — these are branch roots; their presence is expected and correct, not a violation.
  2. Child decisions live in `decisions/*.html` node files and are discovered by following `builds-on`/parent links from their parent, NOT by being listed in `index.html`.
  3. `index_coverage` is satisfied by **reachability**: a page is "covered" if reachable from `index.html` through the link graph (BFS), not only if directly linked from `index.html`.
  4. Graph node files (under `decisions/`, `failure-todos/`, `open-questions/`) are exempt from router-page meta fields (`read-when`, `update-when`, `tracks`) — they carry graph meta (`builds-on`, `status`, `title`) instead.
  5. `ledger.html` is exempt from the 200-line limit — it is a rendered, rotated view, not authored content.
- Lock arbitration: subagents self-manage, orchestrator arbitrates contention
- No limit on subagent count or nesting depth — spawn as many as the task requires; agent-tree and ledger scale to any depth
- Hooks are optional/advisory unless installed and verified in the active runtime

## Known Failure Modes (Claude Code)

Claude Code agents have a strong "helpfulness" objective that conflicts with edit-restriction policies. Even with explicit whitelist procedures, agents will rationalize unauthorized edits when:

1. **Specificity bypass** — A detailed bug description (naming a file, describing root cause) tricks the agent into treating "specificity of the problem" as "permission to edit," skipping the verb check entirely. The agent sees "the user clearly wants this fixed" and acts on inference rather than the literal instruction.

2. **Helpful exhaustion failure** — The decision procedure says "investigate and report" but the agent finishes investigating, has the fix in hand, and edits anyway because "it would be unhelpful to stop here." The DEFAULT ACTION (propose fix, ask permission) exists to give the helpfulness drive an outlet, but agents sometimes skip straight to applying.

3. **Compound sentence parsing** — "X is broken. Handle it." gets parsed as two statements: (a) a specific bug report, (b) an action directive. The agent mentally upgrades the pair to "fix X" even though "handle" is not a qualifying verb.

**Mitigation:** The 4-step decision procedure forces agents to name the verb and check it against the set explicitly. Stress testing shows ~75% compliance on adversarial prompts (vs 15% with prose-based blacklists). Hooks catch the remaining gap for the main session but cannot reach subagents — subagent compliance depends entirely on CLAUDE.md text.
