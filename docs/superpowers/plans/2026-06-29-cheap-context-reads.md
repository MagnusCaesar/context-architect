# Cheap Context Reads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make reading `context/*.html` pages cheap (body-only, no head/infra) and route the framework's default read/gather path through context-mode, propagated to all context instances.

**Architecture:** `extract-body.py` becomes a skill-owned script (copied into every project's `context/scripts/` by bootstrap/refresh). The managed bootloader block (`templates/bootloader-block.md` → each repo's CLAUDE.md/AGENTS.md) is rewritten so the MANDATORY FIRST STEP uses the extractor instead of raw Read, and a READING CONTEXT rule points at `/context-mode:context-mode`. `docs/contracts.md` states the reading-cost contract. A `--refresh` per instance propagates.

**Tech Stack:** Python 3 stdlib (`html.parser`), bash hooks, the existing `bootstrap.py --refresh` machinery.

## Global Constraints

- Skill root: `/shared/home/vrajagopal/.claude/skills/context-architecture`
- `extract-body.py` is skill-owned: lives in `scripts/`, overwritten on refresh, never authored per-project.
- `extract-body.py` preserves links as `text (href)` — never strips navigation.
- extract-body is the HARD default (always present). context-mode is PREFERRED (external MCP, may be absent in headless/cron) — never a hard mandate.
- Bootloader block stays inside `<!-- context-architecture:start -->` / `:end -->` markers; refresh replaces only between them.
- Ponytail: smallest diff. No new deps, no new scripts beyond the one move. Reuse `--demo` as the runnable check.
- Instances to refresh: `PD/eco_timing`, `PD/sdc_copilot-dev`, `PD/timing-mcp`, `~/.claude/firstmate`.

---

### Task 1: Relocate extract-body.py to the skill

**Files:**
- Create: `/shared/home/vrajagopal/.claude/skills/context-architecture/scripts/extract-body.py` (copy of existing firstmate version, unchanged)
- Delete: `/shared/home/vrajagopal/.claude/firstmate/context/scripts/extract-body.py` (refresh re-adds it skill-owned; avoids stale duplicate)

**Interfaces:**
- Produces: CLI `python3 extract-body.py <page.html> [more.html ...]` → title + body-as-text on stdout; `--demo` → asserts + prints `ok`.

- [ ] **Step 1: Copy the script into the skill**

```bash
cp /shared/home/vrajagopal/.claude/firstmate/context/scripts/extract-body.py \
   /shared/home/vrajagopal/.claude/skills/context-architecture/scripts/extract-body.py
```

- [ ] **Step 2: Run the self-check from its new home**

Run: `python3 /shared/home/vrajagopal/.claude/skills/context-architecture/scripts/extract-body.py --demo`
Expected: prints `ok`

- [ ] **Step 3: Remove the firstmate copy (it will be re-added by refresh, skill-owned)**

```bash
rm /shared/home/vrajagopal/.claude/firstmate/context/scripts/extract-body.py
```

---

### Task 2: Rewrite the bootloader block

**Files:**
- Modify: `/shared/home/vrajagopal/.claude/skills/context-architecture/templates/bootloader-block.md`

**Interfaces:**
- Consumes: nothing.
- Produces: managed block copied verbatim into each repo's CLAUDE.md/AGENTS.md on refresh.

- [ ] **Step 1: Replace the MANDATORY FIRST STEP read instructions**

Change the two numbered lines under `### MANDATORY FIRST STEP — NO EXCEPTIONS` from Read-based to extractor-based. Replace:

```markdown
1. **Read `context/index.html`** — this is the project map
2. **Read `context/control-plane.html`** — this tells you which workflow to follow
```

with:

```markdown
1. **Read the map + control plane cheaply** — one call, body-only (no lock/infra noise):
   `python3 context/scripts/extract-body.py context/index.html context/control-plane.html`
2. Read any further `context/*.html` page the same way — `extract-body.py` strips head/tags and keeps links as `text (href)`. Do NOT raw-`cat`/Read context HTML; that burns ~tokens on infra you don't need.
```

- [ ] **Step 2: Add a READING CONTEXT section after the MANDATORY FIRST STEP section (before SOURCE EDIT POLICY)**

Insert:

```markdown
### READING CONTEXT — KEEP IT CHEAP

- **Context pages:** always via `python3 context/scripts/extract-body.py <page.html> ...` (body-only). This is the default, always-available read path.
- **Gathering / processing anything else** (repo files, command output, web): prefer the `/context-mode:context-mode` tools — `ctx_batch_execute` to gather, `ctx_execute_file` to analyze a file, `ctx_search` to recall — so raw bytes stay out of context. Fall back to Read/Bash only when context-mode is unavailable (e.g. headless runs).
```

- [ ] **Step 3: Verify markers intact**

Run: `grep -c 'context-architecture:start\|context-architecture:end' /shared/home/vrajagopal/.claude/skills/context-architecture/templates/bootloader-block.md`
Expected: `2`

---

### Task 3: State the reading-cost contract in docs

**Files:**
- Modify: `/shared/home/vrajagopal/.claude/skills/context-architecture/docs/contracts.md` (around line 295, the existing context-mode mention)

**Interfaces:**
- Consumes: nothing.
- Produces: documentation only; not propagated to repos.

- [ ] **Step 1: Read the existing mention**

Run: `sed -n '290,300p' /shared/home/vrajagopal/.claude/skills/context-architecture/docs/contracts.md`

- [ ] **Step 2: Add one paragraph stating the default read path**

After the existing context-mode recommendation, add:

```markdown
**Reading-cost contract:** context pages are read body-only via
`context/scripts/extract-body.py` (skill-owned, propagated by refresh); raw
`cat`/Read of `context/*.html` is discouraged. For all other gathering and
file analysis, context-mode (`ctx_batch_execute`, `ctx_execute_file`,
`ctx_search`) is the preferred path so raw bytes never enter agent context.
extract-body is always present; context-mode is preferred-when-available.
```

---

### Task 4: Propagate to all instances via refresh

**Files:** none edited — runs `bootstrap.py --refresh` per instance.

**Interfaces:**
- Consumes: Tasks 1–2 (script + bootloader must be final before refresh copies them).

- [ ] **Step 1: Refresh all four instances**

```bash
SKILL=/shared/home/vrajagopal/.claude/skills/context-architecture
for t in /shared/home/vrajagopal/projects/PD/eco_timing \
         /shared/home/vrajagopal/projects/PD/sdc_copilot-dev \
         /shared/home/vrajagopal/projects/PD/timing-mcp \
         /shared/home/vrajagopal/.claude/firstmate; do
  python3 "$SKILL/scripts/bootstrap.py" --target "$t" --refresh
done
```
Expected: each reports updated scripts (incl. `scripts/extract-body.py`) and validate.py result.

- [ ] **Step 2: Confirm the extractor landed and runs in a project repo**

Run: `python3 /shared/home/vrajagopal/projects/PD/eco_timing/context/scripts/extract-body.py --demo`
Expected: `ok`

- [ ] **Step 3: Confirm the bootloader block updated in a project repo**

Run: `grep -c 'extract-body.py' /shared/home/vrajagopal/projects/PD/eco_timing/CLAUDE.md`
Expected: `>= 1` (refresh rewrote the managed block). If `0`, the repo's CLAUDE.md predates managed-block injection — check `AGENTS.md` instead, or report for manual block insertion.

- [ ] **Step 4: Confirm validate still passes in a project repo**

Run: `python3 /shared/home/vrajagopal/projects/PD/eco_timing/context/scripts/validate.py; echo "exit=$?"`
Expected: `exit=0` (pre-existing migration-backlog warnings are acceptable; a new failure referencing extract-body or the bootloader is not).
