# context-architect

Deterministic repo-local context architecture for Codex, Claude Code, and other coding agents.

This project is both:

- a Codex skill, via `SKILL.md`
- a bootstrapper that installs a `context/` control plane into target repositories

The core rule is simple: scripts own routine mechanics; agents own judgment. Locks, ledgers, freshness checks, reachability, routing, validation, generated docs, and agent-tree entries are deterministic script work. Agents decide significance, rationale, whether context should be merged or archived, and how to explain changes.

## Why

Large agent sessions drift when every agent rereads raw files, guesses which notes matter, and freehands coordination state. `context-architect` gives each repository a small local context system:

- map-first retrieval through `context/index.html`
- page-local source ownership through `<meta name="tracks">`
- lock and event history through `ledger.html` plus `ledger-events.ndjson`
- advisory multi-agent visibility through `agent-tree.html`
- durable rationale through `decisions.html`
- orphan/broken-link hygiene through deterministic reachability checks
- bounded generated Markdown docs for humans

It is not a semantic graph database and does not replace context-mode, Graphify, grep, or source reading. It is the enforceable control layer around local project memory.

## Install As A Codex Skill

Normal GitHub install:

```bash
git clone git@github.com:MagnusCaesar/context-architect.git ~/.codex/skills/context-architecture
```

Development checkout install:

```bash
git clone git@github.com:MagnusCaesar/context-architect.git /path/to/context-architecture
ln -s /path/to/context-architecture ~/.codex/skills/context-architecture
```

Then start a fresh Codex session and invoke:

```text
$context-architecture bootstrap this repo
```

or:

```text
Use $context-architecture to add deterministic context architecture to /path/to/project
```

## Bootstrap A Target Repo

From this repository:

```bash
python scripts/bootstrap.py --target /path/to/project --scan
```

Generate the context skeleton:

```bash
python scripts/bootstrap.py --target /path/to/project
```

Import headed existing docs into small HTML pages:

```bash
python scripts/bootstrap.py --target /path/to/project --absorb-docs
```

`--absorb-docs` is intentionally small. It imports headed docs, archives originals under `context/archived/`, links the new pages, and avoids semantic page generation.

## Generated Target Layout

Bootstrap creates:

```text
context/
├── index.html              # Map-first retrieval router
├── control-plane.html      # Runtime checklist
├── ledger-events.ndjson    # Append-only event source
├── ledger.html             # Active locks + bounded event view
├── agent-tree.html         # Advisory active agent subtree
├── decisions.html          # Decision graph and rationale
├── config.json             # Repo roots, roles, validator settings
├── scripts/                # Deterministic tools copied from this repo
├── hooks/                  # Optional runtime hooks
├── docs/                   # Generated Markdown views
├── runtime-policy.md       # OS/sandbox hardening guidance
└── *.html                  # Project context pages
```

The HTML files are the source of truth. Markdown under `context/docs/` is generated for humans.

## Daily Use Inside A Target Repo

Start work:

```bash
python context/scripts/start-task.py --page parser.html --intent "fix parser timing docs"
```

Route changed files to context pages:

```bash
python context/scripts/route-diff.py --files src/parser.py
python context/scripts/route-diff.py --from HEAD~1 --to HEAD
```

Repair page-local source tracking:

```bash
python context/scripts/update-tracks.py --page parser.html --add src/parser.py --remove src/old_parser.py
```

Record advisory subagent state:

```bash
python context/scripts/record-agent.py --agent-id worker-1 --parent-id orchestrator --role verifier --task "validate parser" --page parser.html --status spawned --actor-id orchestrator
```

Check reachability and hygiene:

```bash
python context/scripts/check-reachability.py --json
python context/scripts/daily-hygiene.py --json
```

Close work:

```bash
python context/scripts/close-task.py --page parser.html --summary "updated parser context"
```

Validate anytime:

```bash
python context/scripts/validate.py
```

## Permissions And Hardening

Permission profiles are workflow enforcement, not an OS sandbox. Scripts enforce roles from `context/config.json`:

- `orchestrator`: lock arbitration, stale lock break, track repair, any-agent records
- `worker`: acquire free locks, release own locks, record itself
- `readonly`: read-only checks only

Unknown agents default to `readonly`.

For stronger ledger protection on Linux, run hardening outside the agent runtime as root, an elevated user, or another Unix user that the agent cannot control:

```bash
context/scripts/harden-ledger.sh context
python context/scripts/check-hardening.py --json
```

If the same agent can run `chattr -a`, `chmod`, or arbitrary writes to protected files, hardening is advisory only. See generated `context/runtime-policy.md`.

## Development

This repo is the framework source. `AGENTS.md` and `CLAUDE.md` are maintainer instructions for developing this repository only; they are not bootstrap templates.

Useful checks:

```bash
python /home/vishnu_rajagopal/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
bash smoke.sh
git diff --check
```

The smoke test exercises bootstrap, lock contention, stale lock break, route/freshness, track repair, reachability/hygiene, decision validation, close validation warnings, and docs generation.

## Authoritative Files

- `SKILL.md`: Codex skill instructions
- `docs/contracts.md`: status fields, schemas, metadata contracts, memory boundaries
- `scripts/`: deterministic implementation
- `templates/`: generated target defaults
- `hooks/`: optional hook helpers
- `agents/openai.yaml`: Codex UI metadata

## Design History

`context-architecture-replication-report-2026-06-05.md` is a deprecated historical initial reference. It explains early design exploration, but current behavior is defined by `SKILL.md`, `docs/contracts.md`, scripts, templates, and tests.
