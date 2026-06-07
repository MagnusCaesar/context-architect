# context-architect

Deterministic repo-local context architecture for Codex, Claude Code, and other coding agents.

This project is both:

- a Codex skill, via `SKILL.md`
- a bootstrapper that installs a `context/` control plane into target repositories

The core rule is simple: scripts own routine mechanics; agents own judgment. Humans invoke the skill; the agent runs the deterministic scripts automatically when permissions allow.

## Use

Install this repository as a Codex skill:

```bash
git clone git@github.com:MagnusCaesar/context-architect.git ~/.codex/skills/context-architecture
```

For development, symlink a working checkout instead:

```bash
git clone git@github.com:MagnusCaesar/context-architect.git /path/to/context-architecture
ln -s /path/to/context-architecture ~/.codex/skills/context-architecture
```

Strongly install context-mode too. It keeps large command output, file analysis, web fetches, and indexed search from flooding the model context window:

https://github.com/mksglu/context-mode

Then start a fresh Codex session and ask for the skill:

```text
$context-architecture bootstrap this repo
```

or:

```text
Use $context-architecture to add deterministic context architecture to /path/to/project
```

After bootstrap, keep using the skill for context work:

```text
$context-architecture start work on parser context
$context-architecture route my current diff
$context-architecture update stale tracks
$context-architecture close the parser context task
$context-architecture validate context
```

The agent should run the bundled scripts itself. You should not normally need to
run those scripts manually unless you are debugging, running CI, or operating
without an agent.

What gets installed into a target repo:

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
├── archived/               # Copies of absorbed docs
├── runtime-policy.md       # OS/sandbox hardening guidance
└── *.html                  # Project context pages
```

The HTML files are the source of truth. Markdown under `context/docs/` is generated for humans.

Boundary with context-mode:

- context-mode handles low-context tool execution, indexed retrieval, web/doc fetch indexing, and session-memory search.
- context-architect handles page-local `tracks`, diff-to-page routing, locks, ledger events, agent tree, decisions, reachability/orphan checks, permissions, and generated `context/` structure.

Treat them as complementary. Do not replace deterministic framework scripts with semantic search results.

## Development

This section is for maintaining this framework or debugging the installed scripts directly.

Authoritative files:

- `SKILL.md`: Codex skill instructions
- `docs/contracts.md`: status fields, schemas, metadata contracts, memory boundaries
- `scripts/`: deterministic implementation
- `templates/`: generated target defaults
- `hooks/`: optional hook helpers
- `agents/openai.yaml`: Codex UI metadata
- `smoke.sh`: integration and contract smoke coverage
- `AGENTS.md` and `CLAUDE.md`: maintainer instructions for this framework repo only

Bootstrap a target repo manually:

```bash
python3 scripts/bootstrap.py --target /path/to/project --scan
python3 scripts/bootstrap.py --target /path/to/project
python3 scripts/bootstrap.py --target /path/to/project --absorb-docs
```

Use explicit page input when the scan is not enough:

```bash
python3 scripts/bootstrap.py --target /path/to/project --config /path/to/pages.json
python3 scripts/bootstrap.py --target /path/to/project --pages-json '[{"name":"parser.html","purpose":"Parser context"}]'
```

`--scan` is inventory-only and does not write files. `--absorb-docs` imports headed docs, copies originals under `context/archived/`, links the new pages, and avoids semantic page generation.

Manual target-repo lifecycle commands:

```bash
python3 context/scripts/start-task.py --page parser.html --intent "fix parser timing docs"
python3 context/scripts/start-task.py --page parser.html --intent "audit parser context" --read-only
python3 context/scripts/route-diff.py --files src/parser.py
python3 context/scripts/route-diff.py --from HEAD~1 --to HEAD
python3 context/scripts/check-freshness.py --json
python3 context/scripts/check-freshness.py --page parser.html --json
python3 context/scripts/update-tracks.py --page parser.html --add src/parser.py --remove src/old_parser.py
python3 context/scripts/record-agent.py --agent-id worker-1 --parent-id orchestrator --role verifier --task "validate parser" --page parser.html --status spawned --actor-id orchestrator
python3 context/scripts/check-reachability.py --json
python3 context/scripts/daily-hygiene.py --json
python3 context/scripts/close-task.py --page parser.html --summary "updated parser context"
python3 context/scripts/validate.py
python3 context/scripts/generate-docs.py
```

Daily hygiene also auto-runs once per local day before the first non-`daily_hygiene` ledger event; manual runs are for explicit reports.

Permission profiles are workflow enforcement, not an OS sandbox. Scripts enforce roles from `context/config.json`:

- `orchestrator`: lock arbitration, stale lock break, track repair, any-agent records
- `worker`: acquire free locks, release own locks, record itself
- `readonly`: read-only checks only

Unknown agents default to `readonly`.

For stronger ledger protection on Linux, run hardening outside the agent runtime as root, an elevated user, or another Unix user that the agent cannot control:

```bash
context/scripts/harden-ledger.sh context
python3 context/scripts/check-hardening.py --json
```

If the same agent can run `chattr -a`, `chmod`, or arbitrary writes to protected files, hardening is advisory only. See generated `context/runtime-policy.md`.

Validation:

```bash
python3 /home/vishnu_rajagopal/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
python3 -m py_compile scripts/*.py
bash smoke.sh
git diff --check
```

The smoke test exercises bootstrap/generation, path traversal rejection, unknown-agent permission denial, lock contention, stale lock break, daily hygiene auto-run, route/freshness, track repair/no-op, reachability/hygiene, hardening status, agent lifecycle logging, decision validation, atomic writes, read-only start-task, close validation warnings, and docs generation.

Design history:

`context-architecture-replication-report-2026-06-05.md` is a deprecated historical initial reference. It explains early design exploration, but current behavior is defined by `SKILL.md`, `docs/contracts.md`, scripts, templates, and tests.
