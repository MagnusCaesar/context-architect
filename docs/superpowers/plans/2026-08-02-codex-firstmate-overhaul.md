# Codex Firstmate Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the `contarch-15d5dd0` upgrade and ship one deterministic, mostly invisible context control plane with Claude and Codex adapters, four typed knowledge graphs, Firstmate, role-based model refresh, and reproducible releases.

**Architecture:** Keep the existing HTML context pages, locks, NDJSON ledger, routing, and validation as the shared core. Add small stdlib modules for typed graph parsing, task capsules, platform normalization, and hook dispatch; Claude and Codex own only payload/config rendering. Generated projections and model-visible task capsules are bounded views over authored knowledge, never a second source of truth.

**Tech Stack:** Python 3 standard library, POSIX shell, Git, HTML metadata/links, JSON/NDJSON, Codex `hooks.json`, Codex custom-agent TOML, `codex app-server --stdio` JSON-RPC.

## Global Constraints

- Work only on branch `codex-firstmate-overhaul` in `/home/vishnu_rajagopal/contarch/codex-firstmate-overhaul`.
- Preserve repository-authored `README.md`, `LICENSE`, `AGENTS.md`, `CLAUDE.md`, `agents/`, and the approved 2026-08-02 design spec during archive import.
- Do not import `.pytest_cache`, `__pycache__`, `.pyc`, or generated package artifacts.
- Python and shell standard libraries only; add no dependency.
- HTML remains the authored knowledge source. No database, embeddings, graph service, or duplicate datastore.
- Normal agents receive task facts, decisions, blockers, scope, and links only. They do not receive hygiene internals, complete routers, ledgers, registries, archives, or receipts.
- Preserve legacy `decisions/`, `failure-todos/`, and `open-questions/` paths. Do not bulk-rewrite authored pages.
- Main graph pages contain live HEAD nodes only; every live node is reachable from `index.html` through explicit links.
- Hooks merge managed entries into existing configuration and preserve all unrelated user, project, system, and plugin hooks/instructions.
- Codex compatibility baseline is stable CLI `0.146.0`. Prereleases are watch-only.
- Model roles are `lead -> gpt-5.6-sol/high`, `balanced -> gpt-5.6-terra/medium`, `economy -> gpt-5.6-luna/medium` where supported; actual fallbacks are disclosed.
- Normal sessions never rewrite model policy. Deliberate `--refresh` applies only explicit locally available Codex catalog upgrades.
- Tests never edit global Claude/Codex configuration. Live probes use temporary repositories and sanitized logs.
- Every production behavior follows red-green TDD: run the focused test and observe the expected failure before implementation, then run it green.
- Each task ends with focused tests, the full relevant regression suite, a commit, and an independent subagent review.

---

### Task 1: Import the Archive as a Provenance Commit

**Files:**
- Import from: `/tmp/contarch-archive.YB6fuG`
- Create/modify: all archive files except cache/generated artifacts
- Preserve: `README.md`, `LICENSE`, `AGENTS.md`, `CLAUDE.md`, `agents/`, `docs/superpowers/specs/2026-08-02-codex-firstmate-overhaul-design.md`
- Test: imported `tests/`, `smoke.sh`, syntax checks, installer dry runs

**Interfaces:**
- Consumes: audited 72-regular-file archive tree and baseline commit `5eee25a`
- Produces: one unadapted archive-overlay commit; all later tasks build on it

- [ ] **Step 1: Record the import boundary**

Compute the SHA-256 of both supplied artifacts, confirm the shell payload after
`PAYLOAD_LINE=54` equals the tarball, list safe members, and record current
hashes of every preserved file in the implementer report. Do not add a one-use
import framework to the repository.

- [ ] **Step 2: Import the archive tests first**

Use `apply_patch` to add the archive's `tests/` files without production changes.
Exclude `.pytest_cache`, `__pycache__`, and `.pyc`.

- [ ] **Step 3: Run the red import tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
```

Expected: failures caused by absent archive scripts/hooks or old baseline
behavior. Record the first five distinct expected failure reasons. A collection
error caused by a typo in the applied test patch does not count as red.

- [ ] **Step 4: Apply the vetted archive overlay**

Overlay archive `scripts/`, `hooks/`, `templates/`, `tests/`, historical
`docs/superpowers/`, `SKILL.md`, `docs/contracts.md`, `.gitignore`, `smoke.sh`,
`package.sh`, and `installer-header.sh` with `apply_patch`. Retain current-only
files. Do not remove the older current hook wrappers until the Codex adapter task
reconciles them.

- [ ] **Step 5: Verify the imported baseline**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
python3 -m py_compile scripts/*.py
for test_file in tests/*.sh; do
  case "$test_file" in
    *e2e-subagent-injection.sh) continue ;;
  esac
  bash "$test_file"
done
```

Expected: 37 Python tests pass, 90 smoke assertions pass, six automated shell
tests pass, syntax passes. The manual Claude E2E remains explicitly skipped.

- [ ] **Step 6: Verify preservation and provenance**

Assert preserved-file hashes match Step 1, all imported runtime files match the
archive byte-for-byte, no cache/generated file is tracked, and `git diff
--check` is clean.

- [ ] **Step 7: Commit the provenance overlay**

```bash
git add -A
git commit -m "chore: import contarch-15d5dd0 provenance"
```

---

### Task 2: Parse and Validate Four Typed Knowledge Graphs

**Files:**
- Create: `scripts/knowledge_graph.py`
- Create: `tests/test_knowledge_graph.py`
- Modify: `scripts/validate.py`

**Interfaces:**
- Consumes: context root `Path`
- Produces: `Node`, `load_nodes(context_root)`, `heads(nodes, kind)`, `validate_graphs(context_root, nodes)`

- [ ] **Step 1: Write literal HTML fixtures and failing parser tests**

Create one v2 node per family and legacy decision/failure/open-question fixtures.
The public record is:

```python
@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    status: str
    path: Path
    archived: bool
    parent: str | None
    children: tuple[str, ...]
    related: tuple[str, ...]
    tracks: tuple[str, ...]
    affects: tuple[str, ...]
    statement: str
```

Tests use hand-written expected values:

```python
def test_v2_work_node_parses_minimal_contract(tmp_path):
    root = write_context(tmp_path, {
        "workstreams/work-001-release.html": WORK_NODE_HTML,
    })
    node = load_nodes(root)[0]
    assert (node.node_id, node.kind, node.status) == (
        "work-001-release", "work", "active"
    )
    assert node.parent is None
    assert node.statement == "Ship a reproducible tagged package."

def test_legacy_open_question_normalizes_as_work_question(tmp_path):
    root = write_context(tmp_path, {
        "open-questions/question-001-api.html": LEGACY_QUESTION_HTML,
    })
    node = load_nodes(root)[0]
    assert node.kind == "work"
    assert node.status == "backlog"
```

- [ ] **Step 2: Run the parser tests red**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_knowledge_graph.py
```

Expected: import failure for missing `knowledge_graph`.

- [ ] **Step 3: Implement minimal parsing**

Use current regex/HTML helpers from `check-failure-todos.py` and
`validate.py`. Infer node kind from its path. New/touched nodes declare contract
version 2; untouched legacy shapes remain readable. Do not build a general HTML
DOM or property-graph abstraction.

Allowed statuses:

```python
STATUSES = {
    "wiki": {"active", "superseded", "deprecated"},
    "decision": {
        "proposed", "accepted", "implemented", "superseded",
        "deprecated", "rejected",
    },
    "failure": {"open", "authorized", "blocked", "resolved", "deprecated"},
    "work": {"backlog", "active", "blocked", "done", "cancelled"},
}
```

- [ ] **Step 4: Write adversarial graph tests**

Add table-driven literal cases for:

```python
INVALID_CASES = {
    "duplicate id": "duplicate node id dec-001-cache",
    "invalid status": "invalid work status proposed",
    "empty statement": "missing durable statement",
    "unknown child": "unknown child work-999-missing",
    "cross-family parent": "work node parent must be work",
    "archived parent": "live node cannot use archived parent",
    "one-sided link": "parent/child link is not reciprocal",
    "parent cycle": "parent cycle",
    "wrong directory": "decision node stored outside decisions",
}
```

For every case, assert `validate_graphs()` returns the literal diagnostic and
does not mutate any fixture file.

- [ ] **Step 5: Run adversarial tests red, then implement validation**

Implement global unique IDs, family/status validation, exact file/fragment link
resolution, reciprocal parent/child checks, live-parent checks, and cycle
detection for hierarchy edges. Return all deterministic errors sorted by path
and message.

- [ ] **Step 6: Replace duplicate validator parsing**

Make `validate.py` call `load_nodes()` and `validate_graphs()`. Remove only the
decision parsing now owned by the shared module; preserve lock, ledger, tracks,
permissions, and page-length checks.

- [ ] **Step 7: Verify and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_knowledge_graph.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts/knowledge_graph.py scripts/validate.py tests/test_knowledge_graph.py
git commit -m "feat: add typed context graph validation"
```

---

### Task 3: Enforce HEAD-Only Routers and BFS Discovery

**Files:**
- Create: `tests/test_graph_routers.py`
- Modify: `scripts/bootstrap.py`
- Modify: `scripts/knowledge_graph.py`
- Modify: `scripts/validate.py`
- Modify: `scripts/check-failure-todos.py`
- Modify: `scripts/check-commit-context.py`
- Modify: `scripts/route-diff.py`
- Modify: `templates/config.json`, `templates/page.html`, `smoke.sh`

**Interfaces:**
- Consumes: `load_nodes()` from Task 2
- Produces: `router_heads()`, `reachable_nodes()`, four bootstrap routers and node directories

- [ ] **Step 1: Write router pass/fail tests**

Tests construct a two-level graph in every family. Assert:

```python
def test_router_contains_all_and_only_live_heads(tmp_path):
    root = graph_fixture(tmp_path)
    errors = validate_graphs(root, load_nodes(root))
    assert errors == []
    assert [n.node_id for n in router_heads(root, "decision")] == ["dec-001-root"]

@pytest.mark.parametrize("mutation, expected", [
    ("list_child_on_router", "router contains non-head dec-002-child"),
    ("omit_live_head", "router omits live head dec-003-other"),
    ("link_wrong_family", "decision router links work node work-001"),
    ("remove_parent_backlink", "parent/child link is not reciprocal"),
    ("list_archived_node", "router contains archived node"),
    ("break_child_href", "unreachable live node dec-002-child"),
])
def test_router_invariants(tmp_path, mutation, expected):
    root = mutated_graph_fixture(tmp_path, mutation)
    assert expected in validate_graphs(root, load_nodes(root))
```

- [ ] **Step 2: Run router tests red**

Expected: missing router APIs and bootstrap pages.

- [ ] **Step 3: Implement four concise routers**

Bootstrap creates:

```text
context/wiki.html
context/wiki/archived/
context/decisions.html
context/decisions/archived/
context/failure-todos.html
context/failure-todos/archived/
context/workstreams.html
context/workstreams/archived/
context/history.html
```

`index.html` links the four routers and operational pages. Router graph sections
contain HEAD entries only. Navigation/archive links remain outside graph
sections. Existing root project pages normalize as Wiki nodes; existing paths
do not move.

- [ ] **Step 4: Replace exhaustive index coverage with BFS reachability**

Remove `validate.py:check_index_coverage()`. Use explicit href traversal from
`index.html`; require every live context HTML file to be reachable while archive
navigation remains reachable without turning archived nodes into live HEADs.

- [ ] **Step 5: Route all typed nodes through the shared parser**

Update failure blocking, commit recognition, and diff routing to consume
`load_nodes()` rather than independent decision/failure regex parsers. Preserve
the behavior that only an overlapping open failure blocks close; an unrelated
workstream produces routing information but never blocks completion.

- [ ] **Step 6: Run regressions and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_graph_routers.py tests/test_knowledge_graph.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts templates tests/test_graph_routers.py smoke.sh
git commit -m "feat: enforce head-only context routers"
```

---

### Task 4: Generate History and Suggest Head Consolidation

**Files:**
- Create: `tests/test_history_hygiene.py`
- Modify: `scripts/knowledge_graph.py`
- Modify: `scripts/generate-docs.py`
- Modify: `scripts/context_utils.py`
- Modify: `scripts/close-task.py`
- Modify: `scripts/daily-hygiene.py`

**Interfaces:**
- Produces: `render_history(nodes) -> str`, `consolidation_candidates(nodes) -> tuple[dict, ...]`

- [ ] **Step 1: Write deterministic history tests**

Use terminal nodes across all families with literal `archived-at` timestamps.
Assert the rendered rows are ordered by timestamp then stable ID and contain
links, not copied page bodies. A malformed timestamp returns one path-specific
validation error.

- [ ] **Step 2: Write non-mutating consolidation tests**

```python
def test_three_heads_with_exact_affects_target_form_one_candidate(tmp_path):
    nodes = heads_with_affects("src/cache.py", count=3)
    assert consolidation_candidates(nodes) == ({
        "basis": "affects:src/cache.py",
        "node_ids": ("dec-001-a", "dec-002-b", "dec-003-c"),
    },)

def test_two_heads_do_not_form_candidate():
    assert consolidation_candidates(heads_with_affects("src/cache.py", 2)) == ()

def test_hygiene_never_rewrites_authored_nodes(tmp_path):
    root = graph_fixture(tmp_path)
    before = authored_hashes(root)
    run_daily_hygiene(root)
    assert authored_hashes(root) == before
```

Also prove case-different unrelated paths, similar titles, and shared generic
words do not merge.

- [ ] **Step 3: Run focused tests red, then implement**

Generate `history.html` from terminal archived nodes only. Suggest consolidation
only for three or more live HEADs sharing an exact normalized `affects`, explicit
topic, or source-owner prefix. Store candidate IDs/signature/count in the ledger
event; never edit authored graph pages.

- [ ] **Step 4: Wire generation and commit**

Generate history after bootstrap, successful close, and docs generation.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_history_hygiene.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts tests/test_history_hygiene.py
git commit -m "feat: add context history and head hygiene"
```

---

### Task 5: Share One Context Root Across Git Worktrees

**Files:**
- Create: `tests/test_canonical_context_root.py`
- Modify: `scripts/context_utils.py`
- Modify: `scripts/bootstrap.py`

**Interfaces:**
- Produces: `canonical_context_root(cwd: Path) -> Path`, locator `.git/context-architecture.json`

- [ ] **Step 1: Write real Git-worktree tests**

Create a temporary Git repository, bootstrap context in its main checkout, add a
linked worktree, and assert:

```python
assert canonical_context_root(main_checkout) == main_checkout / "context"
assert canonical_context_root(linked_worktree) == main_checkout / "context"
```

Acquire a page lock and append a ledger event from one checkout; verify the
other sees both. Add pass cases for a non-Git project local fallback.

- [ ] **Step 2: Write adversarial locator tests**

Cover malformed JSON, a relative escape (`../../other/context`), missing target,
target outside the repository's registered root, and a copied worktree-local
`context/`. Each returns one actionable error and never silently chooses the
copy.

- [ ] **Step 3: Run red, then implement atomic locator handling**

Bootstrap writes the canonical absolute context path under Git's common
directory using a temporary file and `os.replace`. `find_context_root()` checks
the locator first and retains the existing no-Git local fallback.

- [ ] **Step 4: Verify callers and commit**

Existing task, close, validation, hook, lock, and ledger callers inherit the
resolver through `context_utils`; do not add parallel lock implementations.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_canonical_context_root.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts/context_utils.py scripts/bootstrap.py tests/test_canonical_context_root.py
git commit -m "feat: share context across git worktrees"
```

---

### Task 6: Build Invisible Task Capsules and Receipts

**Files:**
- Create: `scripts/task_capsule.py`
- Create: `tests/test_task_capsules.py`
- Modify: `scripts/start-task.py`
- Modify: `scripts/context_utils.py`
- Modify: `templates/config.json`

**Interfaces:**
- Produces: `build_capsule(context_root, task, paths, role, max_chars=4000)`, `record_receipt(...)`, `restore_capsule(...)`

- [ ] **Step 1: Write bounded-capsule tests**

Assert a scoped task includes its task/result, accepted decisions, applicable
failure/work blockers, allowed paths, and at most eight node links. Assert the
serialized capsule is at most 4000 characters and truncation is deterministic.

```python
FORBIDDEN_MODEL_TEXT = (
    "ledger-events.ndjson", "mutex", "receipt_id", "daily_hygiene",
    "project-registry", "archived-at", "hookSpecificOutput",
)

def test_capsule_excludes_hygiene_and_unrelated_nodes(tmp_path):
    capsule = build_fixture_capsule(tmp_path, paths=["src/cache.py"])
    assert "Cache keys include tenant ID." in capsule.text
    assert "Unrelated parser decision" not in capsule.text
    assert all(term not in capsule.text for term in FORBIDDEN_MODEL_TEXT)
```

- [ ] **Step 2: Write receipt and restoration adversarial tests**

Receipt ledger events contain node IDs, SHA-256 hashes of exact source bytes,
timestamp, session/turn, budget, and optional restoration lineage. They never
appear in capsule text. Changed node bytes create a new receipt; stale text is
not replayed. Reject missing nodes, paths outside canonical context, and
cross-project nodes.

- [ ] **Step 3: Run red, then implement the minimal boundary**

Reuse typed nodes and existing track matching. One config pair is enough:

```json
{
  "taskCapsuleMaxChars": 4000,
  "taskCapsuleMaxNodes": 8
}
```

Append receipts through the existing ledger mutex. Do not create a receipt
database or expose receipts in model output.

- [ ] **Step 4: Wire start-task and commit**

`start-task.py` may return the capsule for hook consumption, but keeps hygiene
diagnostics in a referenced file. Post-compact restoration rebuilds from current
node hashes and records lineage.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_task_capsules.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts/task_capsule.py scripts/start-task.py scripts/context_utils.py templates/config.json tests/test_task_capsules.py
git commit -m "feat: route bounded task context"
```

---

### Task 7: Add Explicit Claude/Codex Platform Adapters

**Files:**
- Create: `scripts/platforms.py`
- Create: `tests/test_platform_adapters.py`
- Create: `templates/bootloader-core.md`
- Create: `templates/bootloader-claude.md`
- Create: `templates/bootloader-codex.md`
- Modify: `scripts/bootstrap.py`
- Modify: `installer-header.sh`
- Delete after parity: `templates/bootloader-block.md`

**Interfaces:**
- Produces: `resolve_platform(explicit, env, homes)`, `render_bootloader(platform)`, managed-block upsert/install functions

- [ ] **Step 1: Write platform selection tests**

Literal cases:

```python
@pytest.mark.parametrize("explicit, claude_home, codex_home, expected", [
    ("claude", True, True, ("claude",)),
    ("codex", True, True, ("codex",)),
    ("both", True, True, ("claude", "codex")),
    (None, False, True, ("codex",)),
    (None, True, False, ("claude",)),
])
def test_platform_resolution(explicit, claude_home, codex_home, expected):
    assert resolve_platform(explicit, {}, homes(claude_home, codex_home)) == expected

def test_ambiguous_dual_install_requires_explicit_platform():
    with pytest.raises(PlatformError, match="choose --platform claude|codex|both"):
        resolve_platform(None, {}, homes(True, True))
```

- [ ] **Step 2: Write managed-block preservation tests**

Prove authored text before/after markers survives byte-for-byte, repeated refresh
is idempotent, malformed/nested markers fail without writing, Claude output has
no Codex collaboration vocabulary, and Codex output has no Claude tool/slash
commands.

- [ ] **Step 3: Run red, then implement the small adapter seam**

Use plain functions and two concrete render paths, not a class hierarchy.
Bootstrap accepts `--platform claude|codex|both`; refresh uses stored choice and
never redetects. Report when a new session is needed for instructions to reload.

- [ ] **Step 4: Verify installer profiles and commit**

Dry-run Claude-only, Codex-only, and dual installation. Dry runs create no
directory or backup.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_platform_adapters.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts/platforms.py scripts/bootstrap.py installer-header.sh templates tests/test_platform_adapters.py
git commit -m "feat: add explicit harness adapters"
```

---

### Task 8: Normalize and Dispatch Claude/Codex Hooks

**Files:**
- Create: `scripts/hook_dispatch.py`
- Create: `tests/test_hook_dispatch.py`
- Create: `tests/fixtures/hooks/claude-*.json`, `tests/fixtures/hooks/codex-*.json`
- Modify: `scripts/platforms.py`, `scripts/bootstrap.py`
- Reconcile/delete superseded non-Git shell wrappers under `hooks/`
- Preserve: `hooks/pre-commit`, `hooks/post-commit`

**Interfaces:**
- Produces: `normalize_event(event_name, payload)`, `dispatch(event, context_root)`, `merge_hook_config(existing, managed)`

- [ ] **Step 1: Write payload-normalization tests**

Cover Claude `Edit`/`Write` with `tool_input.file_path`, Codex `apply_patch`
with multi-file patch text under `tool_input.command`, Bash, collaboration tool
names such as `collaborationspawn_agent`, session/turn/agent IDs, permission
mode, model, malformed JSON, missing fields, and paths containing spaces.

```python
def test_codex_apply_patch_extracts_every_affected_path():
    event = normalize_event("PreToolUse", CODEX_MULTI_FILE_PATCH)
    assert event.tool == "apply_patch"
    assert event.paths == (Path("a.py"), Path("dir with space/b.py"))

def test_pretool_block_uses_codex_permission_decision():
    result = render_codex_result(block("read context first"), "PreToolUse")
    assert result == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "read context first",
        }
    }
```

- [ ] **Step 2: Write hook-config merge tests**

Prove unrelated user/project/plugin entries survive, the managed group is
idempotently replaced, invalid JSON remains byte-identical, and no assumed
ordering exists between concurrently matching hooks.

- [ ] **Step 3: Run red, then implement one dispatcher**

The dispatcher reads one JSON object, normalizes it, calls existing shared
behavior/task capsules, and renders platform output. Use:

- `SessionStart`: thin project/task capsule;
- `UserPromptSubmit`: routing only when relevant;
- `PreCompact`/`PostCompact`: receipt-based bounded restore;
- `PreToolUse`: edit gate and one actionable denial;
- `PostToolUse`: validation/staleness update;
- `SubagentStart`: bounded role/scope capsule, never block;
- `SubagentStop`: valid JSON; continue only for a concrete validation failure;
- `Stop`/`SessionEnd`: capture candidate without dumping it into context.

Do not parse transcript formats or claim hosted-tool coverage. Spill diagnostic
detail to a referenced file when output exceeds the capsule budget.

- [ ] **Step 4: Run hook regressions and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_hook_dispatch.py tests/test_scope_hooks.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts hooks tests/test_hook_dispatch.py tests/fixtures scripts/bootstrap.py
git commit -m "feat: dispatch Codex and Claude lifecycle hooks"
```

---

### Task 9: Make Firstmate Harness-Neutral and Model-Aware

**Files:**
- Create: `scripts/model_policy.py`
- Create: `tests/test_model_policy.py`
- Create: `tests/test_firstmate_lifecycle.py`
- Create: `templates/agents/lead.toml`, `templates/agents/balanced.toml`, `templates/agents/economy.toml`
- Modify: `scripts/bootstrap.py`, `scripts/context_utils.py`
- Modify: `scripts/fm-review.py`, `scripts/seed-registry.py`, `scripts/capture-candidates.py`
- Modify: `templates/config.json`, `SKILL.md`
- Delete after parity: `scripts/wire-global-hooks.py`, `templates/firstmate-review/SKILL.md`

**Interfaces:**
- Produces: neutral Firstmate path resolution, private managed registry, Codex model catalog client, role-profile renderer

- [ ] **Step 1: Write Firstmate lifecycle/privacy tests**

Assert default root is
`${XDG_DATA_HOME:-$HOME/.local/share}/context-architecture/firstmate`,
`CONTEXT_ARCH_FIRSTMATE` wins, legacy `FIRSTMATE_HOME` warns, and explicit
migration copies without deleting the source. Global bootstrap creates registry,
capture inbox, config, and validation state; Git initializes only with
`--init-git`.

Use two registered temporary projects. Session output may contain project name,
root, and short status; assert it contains no other-project node body, capture
text, unregistered path, or repository file content.

- [ ] **Step 2: Write model catalog/upgrade tests**

Use complete literal `model/list` fixtures for Sol, Terra, and Luna. Assert:

```python
assert resolve_roles(CURRENT_CATALOG) == {
    "lead": ("gpt-5.6-sol", "high"),
    "balanced": ("gpt-5.6-terra", "medium"),
    "economy": ("gpt-5.6-luna", "medium"),
}
```

Adversarial cases: missing Luna warns and resolves economy to
`gpt-5.6-terra/low`; unsupported effort warns and selects the model's documented
default; malformed/truncated JSON-RPC, timeout, missing Codex binary, paginated
results, duplicate model IDs, conflicting `upgrade` and `upgradeInfo.model`,
unknown upgrade, unavailable upgrade target, and prerelease-only target preserve
current generated profiles. An explicit available `upgrade.model` updates only
during `--refresh` and reports old/new actual slugs.

- [ ] **Step 3: Run red, then implement the native catalog client**

Use `subprocess.Popen` with a bounded timeout and newline-delimited JSON-RPC to
`codex app-server --stdio`: send `initialize` with experimental API enabled,
send the `initialized` notification, then page through `model/list` with hidden
models included and limit 200 until `nextCursor` is null. Validate required
fields (`id`, `model`, `displayName`, `hidden`, `isDefault`,
`defaultReasoningEffort`, `supportedReasoningEfforts`) before use. No web
scraping and no model-name version guessing.

Store one policy revision in config:

```json
{
  "modelPolicy": {
    "revision": "2026-08-02.1",
    "lead": {"model": "gpt-5.6-sol", "effort": "high"},
    "balanced": {"model": "gpt-5.6-terra", "effort": "medium"},
    "economy": {"model": "gpt-5.6-luna", "effort": "medium"}
  }
}
```

- [ ] **Step 4: Generate profiles and finish Firstmate wiring**

Generate `.codex/agents/*.toml` with role, model, effort, sandbox, and concise
task instructions. Do not teach agents hygiene mechanics. Firstmate project
registration updates only a marker-delimited section and preserves authored
content. Fold review instructions into main docs/skill and remove orphan wiring.

- [ ] **Step 5: Verify and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_model_policy.py tests/test_firstmate_lifecycle.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add scripts templates tests/test_model_policy.py tests/test_firstmate_lifecycle.py SKILL.md
git commit -m "feat: make Firstmate Codex-aware"
```

---

### Task 10: Add Feature, Compatibility, Changelog, and Release Gates

**Files:**
- Create: `CHANGELOG.md`
- Create: `docs/codex-compatibility.md`
- Create: `scripts/release-verify.sh`
- Create: `tests/test_release_package.py`
- Modify: `README.md`, `.gitignore`, `package.sh`, `installer-header.sh`

**Interfaces:**
- Produces: `package.sh <exact-tag>` and reproducible tarball/self-extractor/checksum artifacts

- [ ] **Step 1: Write release failure tests**

In real temporary Git repositories, prove packaging fails for dirty tracked
files, untracked files, absent tag, tag behind `HEAD`, missing changelog entry,
unsafe tar member, failed verification, and payload mismatch. Assert failure
leaves no misleading completed artifact.

- [ ] **Step 2: Run release tests red**

Expected: legacy `package.sh` accepts at least the dirty/untracked case or lacks
the exact-tag interface.

- [ ] **Step 3: Implement exact-tag packaging**

`package.sh <tag>` must:

1. require `git status --porcelain=v1 --untracked-files=all` empty;
2. require `refs/tags/<tag>^{commit}` equals `HEAD`;
3. require a `CHANGELOG.md` heading for the exact tag;
4. run `scripts/release-verify.sh`;
5. build only with `git archive <tag>`;
6. generate SHA-256 checksums;
7. verify self-extractor payload bytes equal the standalone tarball;
8. run Claude-only, Codex-only, and dual installer dry runs with no filesystem
   side effects.

- [ ] **Step 4: Add one release verifier**

`scripts/release-verify.sh` runs smoke, Python tests, automated shell tests,
Python/shell syntax, compatibility fixture tests, and documentation structural
checks. Manual/live E2E remains a separate explicit gate.

- [ ] **Step 5: Write the non-duplicative docs**

- `README.md`: quickstarts and compact feature/capability matrix.
- `CHANGELOG.md`: `Unreleased` plus only real tagged releases.
- `docs/codex-compatibility.md`: verified stable CLI/date, schema fixtures,
  live-probe command/result boundary, known gaps, upstream watchlist.
- `docs/contracts.md`: behavioral authority; link rather than copy it.

- [ ] **Step 6: Run release tests and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_release_package.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
git add README.md CHANGELOG.md docs/codex-compatibility.md docs/contracts.md .gitignore package.sh installer-header.sh scripts/release-verify.sh tests/test_release_package.py
git commit -m "feat: add reproducible release gates"
```

---

### Task 11: Run Live and Adversarial End-to-End Verification

**Files:**
- Create: `tests/e2e-codex-hooks.sh`
- Create: `tests/e2e-context-worktrees.sh`
- Modify: `docs/codex-compatibility.md` with verified results only

**Interfaces:**
- Consumes: complete branch
- Produces: bounded, repeatable compatibility proof without global config edits

- [ ] **Step 1: Write portable isolated E2E harnesses**

The Codex harness creates a temporary trusted project with project-local hooks,
runs `codex exec --ephemeral --dangerously-bypass-hook-trust --sandbox
workspace-write --json --color never`, and logs event names plus sanitized schema
keys only. It must never inspect transcript contents or edit `~/.codex`.

The worktree harness creates a main checkout plus linked worktree and proves both
resolve one context root, contend on one live lock, append one ledger, and see
the same task receipt/history.

- [ ] **Step 2: Exercise hook pass and fail paths**

Require observed pass events: SessionStart, UserPromptSubmit, SubagentStart,
child PreToolUse/PostToolUse for `apply_patch` and Bash, SubagentStop, parent
Pre/Post tool events. Require fail cases: multi-file patch touching an unowned
path denied, malformed payload fails closed for edits, unrelated existing hook
survives, oversized diagnostic spills to file, and child validation failure asks
the child to continue once.

Stop/SessionEnd absence caused by a bounded run is recorded as inconclusive, not
reported as pass.

- [ ] **Step 3: Exercise graph/capsule adversarial lifecycle**

In temporary projects:

- inject only a bounded relevant capsule into a child;
- verify no ledger/receipt/other-project content appears;
- create a cyclic or router-polluting graph edit and prove validation fails while
  the lock remains;
- repair it and prove close succeeds, history updates, and both worktrees see the
  same result;
- corrupt the model catalog response and prove generated profiles remain intact.
- invoke the generated economy profile and record the actual child model; if the
  active spawn surface rejects Luna, prove the warned Terra-low fallback is what
  actually ran rather than merely changing a label.

- [ ] **Step 4: Run the complete fresh verification gate**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
bash smoke.sh
python3 -m py_compile scripts/*.py
for script in hooks/*.sh tests/*.sh scripts/*.sh; do
  bash -n "$script"
done
bash tests/e2e-context-worktrees.sh
bash tests/e2e-codex-hooks.sh
```

Record exact counts, skipped manual Claude tests, CLI version, stable release,
and observed event matrix in `docs/codex-compatibility.md`.

- [ ] **Step 5: Simulate a clean tagged release**

Clone the completed branch into a temporary repository, create a temporary exact
tag with a matching temporary changelog entry, run `package.sh <tag>`, verify
checksums and payload equality, then remove the temporary repository. Do not tag
the real branch.

- [ ] **Step 6: Commit the live verification harness**

```bash
git add tests/e2e-codex-hooks.sh tests/e2e-context-worktrees.sh docs/codex-compatibility.md
git commit -m "test: verify Codex context lifecycle"
```

---

## Final Review and Completion Gate

- Generate a whole-branch review package from merge-base `main` to `HEAD`.
- Dispatch the final reviewer on `gpt-5.6-sol` with the design spec, this plan,
  SDD ledger, and review package.
- Review against every acceptance criterion, including adversarial evidence,
  user-authored-file preservation, hidden hygiene, no global config edits, and
  clean release simulation.
- If findings exist, dispatch one fix agent with the complete list, then one
  scoped re-review. Do not self-fix in the controller.
- Run the full verification gate again after the final reviewed fix.
- Use `superpowers:finishing-a-development-branch` to present integration
  options. Do not merge, push, tag, or delete the worktree without user choice.
