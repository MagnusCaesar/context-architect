# Context Architecture Replication Report

Date: 2026-06-05
Task class: Standard write
Scope: architecture overview only. No project behavior edits. No nested repo edits.

Reader note: local paths and line references in this report are example provenance from one implementation, not dependencies. Another agent can evaluate the architecture without access to `/data/vishn/rl_fuzz`; treat those references as concrete examples of how this instance implemented the pattern.

## Purpose

This report explains how the current `/data/vishn/rl_fuzz` context-management architecture works and how to replicate it in another project with low friction, low drift, low context load, and minimal reliance on LLM-generated data/code.

This is an overview artifact for a later consensus pass. It intentionally avoids restructuring the current context tree.

## Primary Goals

1. Minimal edits: a reusable system should require a small bootstrap surface, then targeted project-specific pages.
2. No drift from past decisions: durable rules, decisions, and commit freshness checks must constrain future agents.
3. Lower context: agents should load the map and only the pages needed for the task.
4. Lower reliance on LLM data/code generation: schemas, validation, claim rendering, generated-artifact checks, and context hygiene should move into deterministic scripts where possible.

## Executive Summary

The current architecture is a local, gitignored, map-first project knowledge graph for agents. `AGENTS.md` is the bootloader. `context/CONTEXT-MAP.md` is the retrieval router. `context/CONTROL-PLANE.md` is the task-time operating procedure. The rest of `context/` is split into narrow, purpose-labelled pages: terms, decisions, rules, reproducibility, module maps, coordination, observability, todos, tools, and generated results.

The best reusable form is probably not "copy this context directory". It should be a three-layer package:

1. **Agent skill**: portable procedure for when and how to use the context architecture.
2. **Bootstrap scaffold**: deterministic script/templates that create the minimum `AGENTS.md` snippet, `context/` skeleton, schemas, `.gitignore` rules, and validators.
3. **Project instance**: local pages generated or filled for each target repo.

The key design distinction is framework versus payload. The framework owns schemas, routing, validation, task classes, coordination, and observability conventions. The project owns domain terms, module maps, run commands, path variables, generated artifacts, and experiment knowledge. Current `context/CONTEXT.md` mixes both framework terms and RLFuzz-specific terms; a reusable system should split these.

## Architecture Rating Snapshot

This rating is for the current architecture as observed during the research pass. It is not a final consensus score for the future framework.

| Aspect | Rating | Assessment |
| --- | ---: | --- |
| Context efficiency | 8.5/10 | Map-first retrieval, narrow pages, discovery blocks, and no bulk-load pattern are strong. This aligns well with current context-engineering practice. |
| Drift resistance | 7/10 | Decisions, ledgers, and commit-context checks help, but missing deterministic validators still allow drift such as stale ledger indexes. |
| Observability | 8/10 | Daily ledgers, spawn tree, failure todos, and open questions make work auditable. The cost is extra manual ritual. |
| Multi-agent coordination | 8/10 | Claims, worktree policy, and parent-owned integration are solid. Claim rendering and overlap validation should be script-owned. |
| Authorization and safety | 8.5/10 | `CONTEXT-RELEVANT`, `FULL AUTH`, and failure-todo gates protect against accidental scope creep. |
| Minimal-edit discipline | 7.5/10 | Task classes and claims help keep edits scoped. Daily ritual overhead can still force nearby context writes. |
| Portability | 6/10 | The architecture is portable in concept, but the instance leaks repo paths, project payload, git-root assumptions, and model-policy assumptions. |
| Framework/payload separation | 5.5/10 | This is the weakest current area. Generic context architecture terms and RLFuzz-specific facts are still mixed in places such as `context/CONTEXT.md`. |
| Automation / low LLM reliance | 5.5/10 | Commit freshness and some generated artifacts are script-owned. Claims, ledgers, validation, map checks, and hygiene are still mostly LLM/manual. |
| Skill/bootstrap readiness | 6.5/10 | The architecture is clear enough to extract, but needs templates, `context/config.json`, validators, and render scripts before it becomes low-friction. |
| External alignment | 8/10 | The design matches progressive disclosure, agent skills, MCP resource/tool split, and semantic/episodic/procedural memory separation. |

Overall: about **7.5/10 as a working local context system** and **6.5/10 as a reusable framework today**.

Highest-value improvements:

1. Add `context/config.json` for repo roots, local/shared mode, model policy, generated dirs, and validator settings.
2. Add `context/tools/validate-context.js`.
3. Add `context/tools/render-claim.js`.
4. Add `context/tools/render-ledger-entry.js`.
5. Split framework terms from project terms.
6. Package skill/bootstrap templates that copy structure, not project facts.

## Current Boot Flow

Boot sequence:

1. `AGENTS.md`
2. `context/CONTEXT-MAP.md`
3. targeted linked context pages
4. `context/CONTROL-PLANE.md` gates when implementation, observability, or context updates are involved
5. deterministic scripts where available

Evidence:

- `AGENTS.md:5-8`: agents must start with `context/CONTEXT-MAP.md`, use `CONTROL-PLANE.md`, and treat `context/` as a local KG/wiki.
- `AGENTS.md:12`: task start requires `node context/tools/check-commit-context.js --json`.
- `CONTEXT-MAP.md:3-12`: map-first retrieval; open only matching linked files.
- `CONTROL-PLANE.md:13-33`: runtime checklist for commit checks, claims, task class, context authority, todos, decisions, ledgers, and subagents.

Important current caveat:

- Parent `/data/vishn/rl_fuzz` is not a git repo, so the default commit-context command fails unless `--repo-root` points to a nested git repo. This should become a bootstrap/config parameter, not a hardcoded assumption.

## Storage Model

### `AGENTS.md`: Bootloader

Role: always-visible project operating contract.

Contains:

- where context lives;
- mandatory startup checks;
- task classes;
- high-level repo orientation;
- command matrix;
- hard path/toolchain warnings;
- coding and PR style.

Should not contain:

- detailed module maps;
- long experiment history;
- generated-artifact inventories;
- full design rationale;
- anything only relevant to one sub-area.

Replication rule:

Keep `AGENTS.md` short enough that loading it every session is acceptable. Use it to point to the map and critical gates, not to carry the whole knowledge base.

### `context/`: Local Project KG/Wiki

Role: targeted, self-evolving local memory.

Evidence:

- `context/README.md:7`: local project KG/wiki, gitignored by design.
- `context/README.md:36-38`: read `CONTEXT-MAP.md` first and cross-link related pages.
- `decisions/0001-local-context-wiki.md:13,17,21-23`: rationale for local gitignored context rather than shared repo docs.

Properties:

- personal/local, not collaborator-facing;
- map-first;
- split by retrieval question;
- small pages;
- explicit read/update triggers;
- append-only observability where history matters.

Replication rule:

Do not force this local wiki to be source controlled. The framework should support both modes, but the current architecture's strongest assumption is "local memory, shared docs elsewhere."

### `bootstrap.md`: Temporary Migration Handoff

Role: temporary continuation file during context relocation/bootstrap only.

Evidence:

- `context/observability/work-ledgers/2026/05/23/ledger.md:18-24`: bootstrap existed during parent relocation.
- `context/observability/work-ledgers/2026/05/23/ledger.md:42-51`: bootstrap removed after refresh completion.

Replication rule:

If a new project is mid-bootstrap, create `bootstrap.md` with unfinished setup tasks and deletion criteria. Delete it once the map/control-plane/context skeleton is complete.

## Core Components

### 1. Retrieval Map

File: `context/CONTEXT-MAP.md`

Responsibilities:

- canonical index of non-daily context pages;
- page discovery contract;
- map governance;
- line-count/splitting policy.

Current rules:

- every page needs a discovery block: `Purpose`, `Read when`, `Update when` (`CONTEXT-MAP.md:16-19`);
- map rows are retrieval-oriented: topic, file, read trigger, update trigger (`CONTEXT-MAP.md:11-13`);
- one primary retrieval question per file (`CONTEXT-MAP.md:13`);
- soft page limit: 120 lines (`CONTEXT-MAP.md:14`);
- split pages when a page answers unrelated questions (`CONTEXT-MAP.md:15`);
- update map when pages are added, split, renamed, removed, or repurposed (`CONTEXT-MAP.md:70-75`).

Replication rule:

The map is the central context-reduction device. The reusable framework should scaffold the map and validator, but project-specific rows must be generated from the target repo.

### 2. Control Plane

File: `context/CONTROL-PLANE.md`

Responsibilities:

- task-time update routing;
- startup checks;
- task classification;
- context authority;
- claims and subagent coordination;
- todo/failure routing;
- ledger rules.

Key gates:

- read map first;
- run commit-context check;
- inspect `failure_todos`;
- classify work as `Read-only`, `Tiny write`, or `Standard write`;
- use `CONTEXT-RELEVANT` authority, not blanket authority;
- create claims for non-trivial edits or delegated work;
- append ledgers for major Standard-write events;
- parent owns coordination files unless delegated.

Evidence:

- `CONTROL-PLANE.md:14-33`: main runtime checklist.
- `CONTROL-PLANE.md:35-40`: no secrets, no raw logs, append-only corrections.
- `context/rules/agent-operating-rules.md:16`: task class definitions.
- `context/rules/agent-operating-rules.md:48-53`: unrecognized commit flow.

Replication rule:

The control plane should be mostly framework-owned. Target projects should customize task-class thresholds only if they have a clear reason.

### 3. Terms / Glossary

File: `context/CONTEXT.md`

Current issue:

- reusable framework terms and RLFuzz-specific project terms are mixed. Generic framework terms appear near `CONTEXT.md:10-28`; RLFuzz-specific terms begin around `CONTEXT.md:29-31`.

Replication rule:

Split into:

- `context/framework/terms.md` or `context/architecture/terms.md`: context-system vocabulary;
- `context/CONTEXT.md`: target-project domain vocabulary.

This reduces drift when the framework is copied across projects.

### 4. Decisions

Directory: `context/decisions/`

Responsibilities:

- durable rationale;
- trade-off history;
- anti-drift constraints.

Relevant current decisions:

- `0001-local-context-wiki.md`: why local gitignored wiki.
- `0002-self-evolving-context-map.md`: why map-first evolution.
- `0003-agent-observability-ledgers.md`: why ledgers/spawn tree.
- `0004-todos-and-failure-todos.md`: why normal todos and failure todos are separate.
- `0005-parallel-write-coordination.md`: why claims/worktrees.
- `0006-git-commit-context-sync.md`: why commit freshness review.
- `0007-rv32ima-runtime-safe-memory-base.md`: project payload, not framework.

Replication rule:

Ship framework ADR templates and seed ADRs for framework choices. Do not ship project ADRs except as examples.

### 5. Rules

Directory: `context/rules/`

Responsibilities:

- standing workflow rules;
- map-first behavior;
- context authority;
- page hygiene;
- task classes.

Evidence:

- `context/rules/agent-operating-rules.md:22-37`: map as entrypoint and facts routed by directory.
- `context/rules/agent-operating-rules.md:92-94`: small, single-purpose, cross-linked pages.

Replication rule:

Framework should own generic operating rules. Project-specific rules should be separate and visibly labelled.

### 6. Coordination

Directory: `context/coordination/`

Responsibilities:

- avoid hidden parallel writes;
- active claim registry;
- claim schema;
- worktree escalation;
- validation expectations.

Evidence:

- `coordination/README.md:14-16`: no hidden parallel writes; claim first.
- `coordination/write-claims.md:7-16`: check active claims, create claim, no overlaps, release after integration.
- `coordination/write-claims.md:18-32`: conflict and stale-claim rules.
- `coordination/write-claims.md:34-39`: active claims are current ownership; ledger is history; spawn tree is delegation graph.
- `coordination/claims/templates/claim-template.md:7-30`: claim schema.
- `coordination/worktree-policy.md:7-14`: when to use worktrees.
- `coordination/worktree-policy.md:16-20`: avoid worktrees for read-only work.

Current automation gap:

Claim files are machine-parseable but generated by the LLM today. There is no `render-claim` script and no claim-overlap validator.

Replication rule:

Make claim generation deterministic. The LLM should choose scope; a script should render the claim and validate overlap/staleness.

### 7. Observability

Directory: `context/observability/`

Responsibilities:

- daily work ledgers;
- subagent spawn tree;
- recognized commits;
- open questions;
- append-only work history.

Evidence:

- `observability/work-ledgers/README.md:7-12`: daily ledger path and no new events in legacy ledger.
- `observability/work-ledgers/README.md:14-20`: append-only ledger rules.
- `observability/work-ledgers/README.md:22-40`: daily ritual and hygiene subagent.
- `observability/subagent-spawn-tree.md:7-23`: parent, child id, role, task, owned scope, status, integration.
- `CONTROL-PLANE.md:30`: parent owns coordination files, ledgers, and spawn tree unless delegated.

Current drift observed:

- `observability/work-ledgers/README.md:58-66` lists known ledgers only through `2026/05/14`, while later ledger directories exist. This was not fixed because this task is an overview with minimal edits. It is exactly the kind of drift a validator should catch.

Optional filesystem hardening:

- On Linux filesystems that support extended attributes, mature ledger files or dated ledger directories can be protected with `chattr +a` to enforce append-only behavior at the filesystem layer.
- `chattr +a <ledger-file>` means the file can only be appended to; truncation, overwrite, rename, and deletion are blocked until the attribute is removed.
- `chattr +a <ledger-directory>` can be used to make a ledger directory additive: new entries/files can be added, but existing children cannot be removed or renamed without maintenance.
- `chattr -a <path>` removes the append-only attribute for explicit maintenance. This should be rare, logged, and treated like a privileged repair action.
- Do not make this a default portable requirement. It is Linux/filesystem/permission dependent, can interfere with legitimate index repair, and should be a local hardening option after validator and maintenance workflows are stable.

Replication rule:

Keep observability append-only, but automate index checks and stale claim checks.

### 8. Todos and Failure Todos

Directory: `context/todos/`

Responsibilities:

- normal follow-up work;
- observed failures;
- authorization boundaries.

Evidence:

- `todos/failure_todos.md:7-15`: report open failures every interaction; do not work them without explicit `FULL AUTH`.
- `todos/failure_todos.md:17-23`: current authority is `CONTEXT-RELEVANT`; failure repair still needs explicit `FULL AUTH`.
- `todos/failure_todos.md:49-51`: no open failures at time of this report.
- `todos/todos.md:16-18`: normal todos exist and are separate from failures.

Replication rule:

This split is worth preserving. Failure todos are not backlog items; they are safety rails and must remain authorization-gated.

### 9. Reproducibility

Directory: `context/reproducibility/`

Responsibilities:

- environment-variable policy;
- setup order;
- path/toolchain hazards.

Reusable part:

- prefer env/config over hardcoded paths (`environment-variables.md:7-17`);
- record setup commands and assumptions.

Project payload:

- RLFuzz variables such as `THEHUZZ_ROOT`, `RL_TOP`, `TEMPLATE_HEX`;
- `RLfuzz_sim` setup order (`rlfuzz-sim-setup.md:7-12`);
- machine-specific path hazards.

Replication rule:

Framework should provide variable-policy template and setup-page schema. Project supplies variables.

### 10. Module Maps

Directory: `context/module-maps/`

Responsibilities:

- project/source-surface maps;
- current main flow;
- project-specific architecture and risk summaries.

Reusable part:

- "module map" page shape and routing rules.

Project payload:

- RLFuzz repo boundaries (`repo-overview.md:9`);
- `RLfuzz_sim` CLI/source map (`rlfuzz-sim.md:15`);
- RLlib implementation/action maps/reward logic (`rllib-implementation.md:16`);
- state experiments (`rllib-state-experiments.md:9`);
- RV32IMA action-space pages (`action-space/index.md:11`, `rv32ima-sampling-counts.md:35`).

Replication rule:

The framework may scaffold empty module-map templates. It must not carry this project's module facts.

### 11. Tools

Directory: `context/tools/`

Currently script-owned:

- `check-commit-context.js`: computes `head`, `recognized`, `needsReview`, `baseCommit`, and `diffRange` from Git plus `observability/recognized-git-commits.md`.
- `--mark-reviewed`: appends recognized HEAD after context review.

Evidence:

- `check-commit-context.js:55`: JSON status computation.
- `check-commit-context.js:70`: output shape includes review/freshness data.
- `check-commit-context.js:109-127`: mark-reviewed write path.
- `check-commit-context.js:130-148`: CLI args including `--repo-root`, `--source`, `--summary`.

Current automation gaps:

- no full context validator;
- no deterministic claim renderer;
- no stale claim sweeper;
- no map/discovery-block/line-limit validator;
- no generic generated-artifact consistency checker.

Replication rule:

The framework should ship tools before expanding prompts. Every schema that can be checked should be checked by code.

## Data Lifecycle

### Startup

The agent receives `AGENTS.md`, then must read `CONTEXT-MAP.md`.

Context load is intentionally small:

- high-level workflow in `AGENTS.md`;
- map entries;
- only targeted context pages.

### Task Routing

Control-plane gates classify work:

- `Read-only`: no writes, no generated artifacts, no state-changing commands.
- `Tiny write`: <=5 changed lines, <=2 files, no behavior/config/path/toolchain/generated-artifact change.
- `Standard write`: anything broader, plus any behavior/config/path/toolchain/generated-artifact update or verification failure.

### Context Mutation

Context is updated only under `CONTEXT-RELEVANT` authority:

- active task;
- observed failure;
- verification result;
- subagent coordination;
- Git commit context sync.

Architecture-level context rule changes require explicit user request or clear intent.

### Observability

For Standard writes:

- create/check claim;
- append daily ledger start;
- record subagent tree if subagents are used;
- append verification/close event;
- release claim.

### Commit Freshness

The intended flow:

1. run `check-commit-context.js --json`;
2. if `needsReview=true`, inspect `diffRange`;
3. update affected context pages;
4. mark reviewed with source and summary.

Current problem:

Default root assumes the parent is a git repo. In this checkout, it is not. Bootstrap must configure one or more repo roots.

## Parallel-Agent Pattern

The current architecture treats subagents as parallel readers/workers with explicit delegation tracking:

- parent owns coordination files by default;
- subagents get disjoint read/write scopes;
- spawn tree records parent/child/task/scope/status/integration;
- subagents can spend large context budgets, but return distilled notes.

This matches the external context-engineering pattern where subagents isolate deep exploration and return condensed summaries.

Replication rule:

Preserve parent ownership of coordination artifacts. Subagents should not edit claims, ledgers, or spawn tree unless explicitly assigned.

## Existing Script-Owned Versus LLM-Owned Work

### Script-Owned Today

Generic:

- commit freshness check;
- mark-reviewed append.

Project payload:

- `THEHUZZ_INTEREST_ACTION_MAP` generation;
- RLlib JSONL conversion/validation;
- PPO reward plotting.

### LLM-Owned Today

- deciding whether a context fact is durable;
- updating wiki pages;
- writing ledgers;
- creating claim files;
- updating spawn tree;
- reviewing `diffRange`;
- checking map/discovery/ledger drift manually.

### Recommended Automation Shift

Add:

```text
context/tools/validate-context.js --json --context-root context --today YYYY-MM-DD
context/tools/render-claim.js --agent <id> --scope <path> --ttl-minutes 45 --dry-run
context/tools/check-generated.js --json
context/tools/render-ledger-entry.js --type start|close|blocker --json
context/tools/context-roots.json
```

The LLM should still make judgment calls, but scripts should own schema, index, overlap, stale, generated-output, and consistency checks.

## Reusable Framework Boundary

Framework owns:

- boot contract;
- context map contract;
- discovery block schema;
- page size/splitting policy;
- control-plane checklist;
- task classes;
- context authority levels;
- claim schema and validator;
- worktree escalation policy;
- ledger schema and append-only policy;
- spawn-tree schema;
- recognized-commit sync protocol;
- failure-todo authorization model;
- reproducibility-page schema;
- module-map page schema;
- deterministic validation tools.

Project owns:

- domain glossary;
- repo boundaries;
- module maps;
- run commands;
- setup order;
- path variables;
- generated artifacts;
- benchmark/vendor exclusions;
- experiment results;
- project-specific ADRs;
- project-specific failure todos.

Do not package:

- generated results;
- action-space counts;
- run IDs;
- benchmark trees;
- RLFuzz paths;
- model names as hardcoded policy;
- daily hygiene worker model as hardcoded policy;
- local machine paths.

## Recommended Replication Package

### Skill Layer

Name idea: `context-architecture` or `self-evolving-context`.

Skill purpose:

- tell agents when to use the architecture;
- read map first;
- run validator;
- classify task;
- create claims;
- route updates;
- preserve framework/payload boundary;
- prefer deterministic scripts.

Skill should include:

```text
SKILL.md
scripts/bootstrap-context.js
scripts/validate-context.js
scripts/render-claim.js
scripts/render-ledger-entry.js
templates/AGENTS-snippet.md
templates/context/CONTEXT-MAP.md
templates/context/CONTROL-PLANE.md
templates/context/README.md
templates/context/framework/terms.md
templates/context/CONTEXT.md
templates/context/rules/agent-operating-rules.md
templates/context/coordination/...
templates/context/observability/...
templates/context/todos/...
templates/context/reproducibility/...
templates/context/decisions/...
examples/minimal-project/
```

### Bootstrap Layer

Bootstrap should ask or infer:

- project name;
- repo root(s);
- whether context is local-only or shared;
- primary language/build/test commands;
- generated/vendor directories to exclude;
- whether subagents are expected;
- whether commit freshness should track one root or many roots.

Bootstrap should write:

- `AGENTS.md` snippet or patch proposal;
- `context/` skeleton;
- `.gitignore` entry if local-only;
- `context/config.json`;
- initial `CONTEXT-MAP.md`;
- initial `CONTROL-PLANE.md`;
- initial decisions for local/shared context and map-first retrieval;
- empty `failure_todos.md`, `todos.md`, `open-questions.md`;
- validator scripts.

Bootstrap should not:

- infer deep module maps without user review;
- hardcode host paths;
- copy this repo's RLFuzz facts;
- mark context reviewed unless it actually inspected the target repo.

### Project Instance Layer

Each target project gets:

```text
context/
  README.md
  CONTEXT-MAP.md
  CONTROL-PLANE.md
  framework/terms.md
  CONTEXT.md
  rules/
  coordination/
  observability/
  todos/
  reproducibility/
  decisions/
  module-maps/
  tools/
```

Optional:

```text
bootstrap.md
```

Only while setup is incomplete.

## Suggested File Split for Current Architecture

For a future cleanup pass, not this report:

```text
context/framework/terms.md
  context architecture
  context map
  control plane
  task class
  claim
  ledger
  spawn tree
  context authority

context/CONTEXT.md
  RLFuzz
  RLfuzz_sim
  nested RLFuzz
  TheHuzz
  action map mode
  state_reward_style
```

This split is the most obvious first debate item for consensus with another agent.

## External Patterns and How They Map Here

### Anthropic Context Engineering

Relevant ideas:

- context is finite and should be treated as a scarce resource;
- the goal is the smallest high-signal context set;
- just-in-time file/tool retrieval beats dumping all data up front;
- folder names, file names, and timestamps act as retrieval metadata;
- subagents isolate deep exploration and return distilled summaries.

Current architecture match:

- `CONTEXT-MAP.md` is the just-in-time router;
- discovery blocks provide metadata;
- page splitting limits context load;
- subagents are recorded in spawn tree and return summaries.

Source:

- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

### Agent Skills

Relevant ideas:

- skills use progressive disclosure;
- agents load only name/description first;
- full `SKILL.md` loads only when needed;
- bundled scripts/resources execute on demand.

Current architecture match:

- `AGENTS.md` is always-visible boot policy;
- `CONTEXT-MAP.md` points to context on demand;
- a reusable version should become a skill plus scripts/templates.

Source:

- https://github.com/agentskills/agentskills

### MCP

Relevant ideas:

- tools are active, schema-defined operations;
- resources are passive read-only context;
- prompts are reusable workflow templates.

Current architecture match:

- `context/` pages are resources;
- `context/tools/*.js` are local tools;
- `CONTROL-PLANE.md` and future skills are prompt/workflow templates.

Future option:

- expose context map search, validation, claim rendering, and commit checks as MCP tools/resources.

Source:

- https://modelcontextprotocol.io/docs/learn/server-concepts
- https://modelcontextprotocol.io/docs/learn/architecture

### OpenAI Agents SDK Memory / Sessions

Relevant ideas:

- sessions persist conversation history and support compaction;
- sandbox-agent memory uses progressive disclosure: small summary first, search memory index, then open rollout summaries when needed;
- memory can become stale and should be guidance, not authority.

Current architecture match:

- local `context/` provides long-lived memory outside session history;
- map-first behavior resembles memory summary -> registry -> detailed rollout;
- commit-context and validation scripts are needed to prevent stale memory from overriding current repo state.

Source:

- https://openai.github.io/openai-agents-js/guides/sessions/
- https://openai.github.io/openai-agents-js/guides/sandbox-agents/memory/
- https://developers.openai.com/cookbook/examples/agents_sdk/session_memory

### LangGraph Memory Taxonomy

Relevant ideas:

- short-term memory is thread/session scoped;
- long-term memory is namespace-scoped;
- semantic memory stores facts;
- episodic memory stores past actions;
- procedural memory stores rules/instructions;
- memory can be written hot-path or in background.

Current architecture mapping:

- semantic: `CONTEXT.md`, module maps, reproducibility pages;
- episodic: daily ledgers, spawn tree, recognized commit history;
- procedural: `AGENTS.md`, `CONTROL-PLANE.md`, rules, skills;
- hot-path writes: task ledgers, failure todos;
- background writes: daily hygiene, context refresh.

Source:

- https://docs.langchain.com/oss/javascript/langgraph/memory

### Academic Context/Manifest Work

Useful signals:

- ACE frames contexts as evolving playbooks and warns against context collapse from iterative rewriting.
- Dual-process memory work separates immediate episodic context from consolidated long-term knowledge.
- Agentic coding manifest studies show project manifests commonly carry operational commands, implementation notes, and architecture, but lack standardization.
- Agent-skills studies show reusable skills are emerging infrastructure, but redundancy and safety risks exist.

Current architecture match:

- append-only ledgers avoid destructive summarization;
- decisions preserve rationale;
- map-first retrieval avoids monolithic manifests;
- skill packaging should keep state-changing actions behind explicit checks.

Sources:

- https://arxiv.org/abs/2510.04618
- https://arxiv.org/abs/2603.18631
- https://arxiv.org/abs/2509.14744
- https://arxiv.org/abs/2602.08004

## Failure Modes

### 1. Monolithic Context Creep

Symptom:

`AGENTS.md` or `CONTEXT.md` becomes a giant manual.

Fix:

Map-first retrieval, page limits, and skill progressive disclosure.

### 2. Framework/Payload Mixing

Symptom:

Generic context architecture terms and project facts live in same page.

Fix:

Split framework terms from project terms. Ship templates, not payload.

### 3. Stale Repo Assumptions

Symptom:

Agent trusts context from an older commit.

Fix:

Commit-context check, configured repo roots, `needsReview` flow, mark-reviewed only after update.

### 4. LLM-Freehand Schema Drift

Symptom:

Claims, ledgers, map rows, or spawn-tree entries slowly change shape.

Fix:

Render and validate with scripts.

### 5. Observability Index Drift

Symptom:

Ledger index omits dated ledgers.

Fix:

Validator checks actual directory tree against README/index.

### 6. Over-Automated Bad Memory

Symptom:

Agent records too many noisy facts because every event becomes "durable."

Fix:

Control-plane authority and explicit routing. Scripts validate shape; LLM/human still decide significance.

### 7. Unsafe Generated Artifact Interpretation

Symptom:

LLM reads large generated data and hand-summarizes wrong facts.

Fix:

Use scripts to compute summaries/checks from raw data.

## Minimal Replication Roadmap

### Phase 0: No-Edit Architecture Agreement

Use this report to agree on:

- skill versus bootstrap versus MCP;
- framework/payload split;
- context root config;
- validation scope;
- local-only versus shared.

### Phase 1: Extract Framework Skeleton

Create a skill with templates only:

- `AGENTS` snippet;
- map;
- control plane;
- rules;
- coordination;
- observability;
- todos;
- decisions;
- reproducibility schema;
- module-map schema.

No target project facts.

### Phase 2: Deterministic Validator

Implement `validate-context.js`:

- all mapped files exist;
- all context markdown pages have discovery block;
- no unmapped non-daily context markdown except allowed templates/archive;
- soft line limit warnings;
- active claim schema valid;
- stale claim warnings;
- claim overlap warnings;
- ledger index matches dated directories;
- daily hygiene marker status;
- recognized-commit file parseable.

### Phase 3: Deterministic Renderers

Implement:

- `render-claim.js`;
- `render-ledger-entry.js`;
- `render-spawn-entry.js`;
- `init-context.js`.

Purpose:

LLM supplies semantic values; scripts supply shape.

### Phase 4: Repo-Root Adapter

Add `context/config.json`:

```json
{
  "contextRoot": "context",
  "localOnly": true,
  "repoRoots": [
    {
      "name": "main",
      "path": "."
    }
  ],
  "generatedDirs": [],
  "vendorDirs": [],
  "dailyHygiene": {
    "enabled": true,
    "model": "configurable"
  }
}
```

Current `/data/vishn/rl_fuzz` would need multiple repo roots because parent is not git:

```json
{
  "repoRoots": [
    { "name": "RLfuzz_sim", "path": "RLfuzz_sim" },
    { "name": "legacy-RLFuzz", "path": "RLFuzz" }
  ]
}
```

### Phase 5: Optional MCP Server

Only after scripts stabilize:

- expose context map as resources;
- expose validator, claim renderer, commit checker as tools;
- expose bootstrap prompts/templates.

This is optional. A skill plus local scripts may be enough.

## Debate Questions for Consensus

### Question 1: Skill, Bootstrap, MCP, or Hybrid?

Recommendation: hybrid.

Use a skill for progressive-disclosure instructions, a bootstrap script for deterministic file creation, and optionally MCP later for tool/resource exposure.

Why:

- skill alone cannot safely generate/validate schemas;
- bootstrap alone does not teach future agents when to use the system;
- MCP first adds infrastructure before the contract is stable.

### Question 2: Local-Only or Shared?

Recommendation: default local-only, configurable shared mode.

Why:

The current architecture assumes personal/local memory. Some teams may want shared framework skeletons, but project-specific agent memory can contain local paths, failures, and work history that should not travel by default.

### Question 3: Framework Terms Split?

Recommendation: yes.

Why:

Current `CONTEXT.md` mixing is the clearest copy hazard. Framework terms should move to a framework-owned page in any reusable package.

### Question 4: How Much Should LLMs Write?

Recommendation: LLMs decide meaning; scripts render and validate structure.

LLM-owned:

- whether a fact is durable;
- what a decision means;
- which page owns a fact;
- summary wording.

Script-owned:

- schema;
- file placement;
- claim overlap;
- map links;
- discovery blocks;
- ledger index;
- generated-output consistency.

### Question 5: Should Daily Hygiene Be Mandatory?

Recommendation: configurable default, not hardcoded law.

Why:

It is useful in this repo, but model choice, frequency, and strictness should be project config.

### Question 6: What Is the Atomic Memory Unit?

Recommendation: page for semantic/procedural knowledge, ledger entry for events, decision record for rationale, claim file for current ownership.

Why:

This preserves type-specific retrieval and avoids one giant memory blob.

## Concrete First-Pass Skill Shape

`SKILL.md` should be short:

```markdown
---
name: context-architecture
description: Bootstrap and operate a map-first local context wiki for agent work, with deterministic validation and low context load.
---

Use when the user wants persistent project context, agent memory architecture, self-evolving context, or low-drift multi-agent coordination.

Workflow:
1. Run `scripts/bootstrap-context.js --dry-run` if no context exists.
2. Read `<contextRoot>/CONTEXT-MAP.md`.
3. Run `scripts/validate-context.js --json`.
4. For work, follow `<contextRoot>/CONTROL-PLANE.md`.
5. Prefer render scripts for claims/ledgers/spawn entries.
6. Keep framework pages separate from project payload pages.
```

Full instructions can live below with links to templates/scripts.

## What To Preserve Exactly

Preserve:

- map-first retrieval;
- discovery block;
- one retrieval question per page;
- soft size cap;
- `Read-only` / `Tiny write` / `Standard write`;
- `CONTEXT-RELEVANT` authority;
- normal todo versus failure todo split;
- append-only ledgers;
- explicit subagent spawn tree;
- cooperative write claims;
- commit freshness check;
- local-only default;
- project facts kept out of framework.

Do not preserve as framework law:

- RLFuzz path names;
- specific action-space pages;
- exact model choices for hygiene;
- current parent-root git assumption;
- current ledger-index drift;
- generated plot/result directories;
- old sibling/nested repo semantics.

## Final Recommendation

The next architecture should be a portable skill-driven bootstrap framework with deterministic scripts. The skill should teach the workflow. The bootstrap should create the files. Validators should enforce the contract. Project payload should remain separate from framework context.

The first implementation should not try to become a database or MCP server. Start with files plus scripts because that matches the current architecture, is inspectable, works offline, and keeps edits minimal. Add MCP only after the file contracts are stable.
