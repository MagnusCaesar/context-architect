---
name: firstmate-review
description: On-demand cross-project first-mate review. Runs context hygiene over every registered project and proposes reduce/reuse opportunities into the first-mate suggestions inbox. Use when the user says "/firstmate-review", "first mate review", "review my projects", or asks for cross-project cleanup ideas.
---

# First-mate Review

On-demand. Two passes, pull-not-push: the advisor writes to an inbox the captain
reads when they want. It never edits project code and never writes the live
decision graph.

## Pass 1 — Hygiene (deterministic, reuses existing scripts)

Run the orchestrator and report the result verbatim as a short table:

```bash
python3 ~/.claude/skills/context-architecture/scripts/fm-review.py --firstmate ~/.claude/firstmate
```

- One line per registered project: validate / hygiene / reachability status.
- Surface any `DEAD:` paths (registry entries whose `context/` is gone) and offer
  to re-run `seed-registry.py` to refresh the registry.
- If any project shows validate FAILs, list them. Do NOT fix them here; report.

## Pass 2 — Advisor (judgment, writes to inbox only)

Read the registered projects' `context/index.html` + domain pages (use the paths
from the registry) and look for genuine reduce/reuse opportunities ACROSS projects:
duplicated parsing/util logic, two projects solving the same problem differently,
a helper in one that the other reinvents. For EACH real opportunity, deposit ONE
candidate into the first-mate inbox (never edit project code, never write a live
decision):

```bash
python3 ~/.claude/firstmate/context/scripts/capture-candidates.py \
  --inbox ~/.claude/firstmate/context/capture-inbox.html \
  --kind open-question \
  --summary "<one-line reduce/reuse opportunity>" \
  --source firstmate-review
```

Rules for the advisor:
- Only propose opportunities you can point at concretely (name the files/pages).
  No speculative "you could refactor X someday."
- If you find nothing worth proposing, say so and write nothing. Silence is a
  valid result; do not manufacture suggestions.
- Dedup is handled by capture-candidates.py (it skips matching pending entries).

## Output

Report the hygiene table, the count of advisor candidates deposited (and where to
read them: `~/.claude/firstmate/context/capture-inbox.html`), and any dead paths.
Nothing else is changed.
