# Context recovery and efficiency audit

Baseline: `3d3ab7851f3afed5423da7b0ca9fdf5db8b925d6`. Three GPT-6 Luna
subagents reviewed recovery, hooks, and efficiency independently. Findings
below are open recommendations, not implemented fixes. The accompanying
model-policy update changes defaults and documentation only.

Goal: a working agent receives the right current task, constraints, evidence,
decisions, and blockers after start, delegation, compaction, or resume, without
running context-management commands. Scripts own persistence and routing;
models own semantic judgment. Existing automated checks do not establish this
end-to-end outcome.

## Highest-priority correctness and automation gaps

| Priority | Finding and evidence at baseline | Smallest useful change | Proof required |
| --- | --- | --- | --- |
| P1 | Ordinary project prompts inject nothing. `hook_dispatch.py:486-495` makes SessionStart inert and gates UserPromptSubmit on a Firstmate route. `platforms.py:141-145` installs SessionStart only globally. A fresh-project fixture returned zero capsule characters. | Establish active task context for normal project turns; inject a bounded snapshot at supported start/resume/prompt boundaries, with an explicit no-task path. | A generated project receives relevant context on its first ordinary task, then recovers the task after compaction. |
| P1 | Routed project recovery searches the wrong root. `_capsule_for_event` writes to the routed project (`hook_dispatch.py:350-367`), but PostCompact searches cwd's root (`371-382`). A temporary workbench-to-beta fixture injected a capsule then restored nothing. | Persist an atomic, private session/agent/task-to-project receipt locator. Validate project identity and registry authorization when restoring. | Routed prompt followed by compaction at the original workbench cwd recovers only beta's context. No broad cross-project search. |
| P1 | Ledger rotation hides recovery state. `context_utils.py:966-1009` moves old events to archives; receipt validation (`task_capsule.py:341-358`) and latest-receipt selection search active events only. A backdated receipt became unresolvable after rotation. | Keep a bounded active-task checkpoint independent of ledger rotation, referencing verifiable active or archived receipt evidence. | A cross-day restore survives rotation; corrupt or mismatched evidence is still rejected. |
| P1 | Normal project Stop captures nothing. `bootstrap.py:1468-1469` creates the inbox only globally; Stop targets the project; `context_utils.py:93-95` returns false if its inbox is absent. Confirmed with fresh project bootstrap. | Provide an explicit project capture destination and record capture success/failure privately. Add durable promotion separately; an inbox entry alone is not recoverable knowledge. | Project Stop persists its candidate, and a later recovery can access accepted knowledge through the normal scoped graph. |
| P1 | Required agent chores conflict with the goal. `templates/bootloader-core.md:6-36` demands map/control reads and manual updates. Its prescribed `extract-body.py` shell call cannot satisfy read markers, which only native Read sets (`hook_dispatch.py:503-505`, `platforms.py:157`). | Hook-delivered page content should satisfy the read gate through a content-hash delivery receipt. Retain a manual fallback only when delivery is unavailable. | A tracked edit succeeds after valid automatic delivery; changed context invalidates the receipt and triggers delivery again. |
| P1 | Capsule selection can omit a requested blocker. `_nodes` sorts by kind/id/path (`task_capsule.py:169-171`), then `build_capsule` takes eight nodes (`222-224`). Eight decisions can crowd out a linked work/task blocker. | Reserve room for explicit task links and blocking constraints before general relevant facts; report overflow privately and use bounded expansion when needed. | More than eight relevant nodes cannot silently displace required linked constraints. |
| P2 | Hook capsule construction ignores `taskCapsuleMaxChars`. The template has the setting, but `build_capsule` reads only MaxNodes (`task_capsule.py:209-216`); the hook supplies no explicit limit. A 200-character setting produced 1,245 characters. | Enforce both configuration ceilings in the shared builder, including header allocation. | The same configured ceiling applies to direct, hook, and restored capsules. |

## Speed and token cost

- **Whole-tree capsule work.** `task_capsule.py:144-152` traverses all HTML for
  path checks, then `knowledge_graph.py:137-143` traverses and parses it again.
  Selected pages are reread for metadata and hashes. Consolidate those reads
  first. Add an invalidated index only if file/byte counts and latency justify
  it; retain path confinement and visibility checks on every lookup.
- **Full-ledger work on each append.** `append_ledger_record` renders HTML after
  every receipt (`context_utils.py:612-616`). Rendering parses the entire
  NDJSON history before showing a limited tail (`586-600`, `643-649`). For N
  events of similar size between rotations, cumulative parse work grows
  quadratically. Tail-read the projection and use direct checkpoint/receipt
  lookup for recovery. Preserve the append-only audit source.
- **Repeated Git processes.** `write_atomic` calls `warn_dirty_target`
  (`context_utils.py:465-511`), performing repository/status checks for each
  lifecycle page write. Collect dirty paths once per transaction.
- **Repeated diagnostics.** Source-edit PostToolUse calls full freshness work
  (`hook_dispatch.py:304-316,511`), including Git history queries per track.
  Route changed paths to affected pages, batch Git queries, and inject only
  changed actionable results. A successful routine check should be quiet.

No speedup or token-saving percentage was measured. Measure files/bytes read,
subprocess count, p50/p95 hook latency, injected characters (and tokens when a
runtime tokenizer is available), and duplicate delivery rate on identical
workloads. Avoid adding a service or database until simpler changes are measured.

## Lifecycle and identity gaps

The active-work CLI is useful but hooks do not yet drive task/question state
transitions. Hook data needs stable task, parent/child, session, and project
identity before automated transitions are reliable. Current restore chooses a
session's last receipt without a distinct task/agent selector. Completed-task
supersession is a follow-up concern; a full close/new-task reproduction was not
run in this audit.

Permission documentation also disagrees: repository `AGENTS.md` requires
unknown actors to be readonly, while generated defaults assign worker
(`templates/permission-profiles.json:3`, `context_utils.py:357-362`). The fresh
fixture confirmed an unregistered child resolves to worker. Make the trusted
harness register children with explicit capabilities; unknown IDs should retain
the documented readonly boundary. Runtime enforcement remains separate from
advisory model instructions.

## Proposed automatic flow

1. The harness records the active task and exact parent/child/project identity
   from supported events, with an explicit capability check for each runtime.
2. Start, resume, and compaction restore a checkpoint and inject current task
   constraints plus relevant durable nodes. File access supplies concrete scope
   when the initial prompt does not. Unchanged context is not repeatedly sent.
3. Tool/lifecycle events maintain locks, dirty paths, evidence, and task state
   through deterministic scripts. Successful housekeeping stays invisible.
4. If semantic capture is needed, a bounded Luna capture subagent extracts
   candidate facts/decisions from authorized task events. It supplies structured
   output with source references; deterministic code validates, deduplicates,
   persists, and records provenance. Work agents do not write context HTML.
5. Task close creates the next resumable checkpoint. A private failure status
   exposes broken capture/recovery to diagnostics rather than silently treating
   an empty capsule as successful restoration.

Deterministic tools cannot infer an unrecorded decision from arbitrary prose.
The capture subagent supplies that judgment; scripts control its inputs and
writes. Human decisions and acceptance remain explicit. No automatic task
completion or authorizing work merely because it is ready.

## Implementation order and acceptance gate

First fix initial delivery, project capture, routed restore, and rotation
survival. Next remove read/update chores through verified delivery and capture.
Then fix capsule budgets/required-node selection and optimize measured hot paths.

The acceptance scenario should start a task, delegate bounded work, record a
decision and blocker, compact, rotate the ledger, resume in a linked worktree,
and continue the correct task without a work agent running a context command.
Assert preserved constraints, current facts, correct project/agent identity,
no unrelated/private nodes, bounded context, and zero housekeeping prompts.
Add duplicates, missing events, and changed source nodes to the same scenario.

Live Codex/Claude lifecycle delivery was not exercised in this audit. Preserve
the dated observations in `codex-compatibility.md`; current schema fixtures and
successful direct Luna delegation do not prove every lifecycle event is delivered.
