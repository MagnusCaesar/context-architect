# context-architect

Deterministic, repo-local context architecture for Codex and Claude Code. Scripts own routing, locks, receipts, and validation; models see only the small task context needed for current work.

## Quick start

Install as a Codex skill from a checkout:

```bash
git clone git@github.com:MagnusCaesar/context-architect.git ~/.codex/skills/context-architecture
```

Or use a tagged self-extractor:

```bash
sh contarch-vX.Y.Z.sh --platform codex
# also accepted: --platform claude | --platform both
```

Start a fresh session, then bootstrap explicitly:

```text
Use $context-architecture to bootstrap this repo for Codex.
```

Equivalent maintainer commands:

```bash
python3 scripts/bootstrap.py --target /path/to/project --platform codex
python3 scripts/bootstrap.py --target /path/to/project --platform claude
python3 scripts/bootstrap.py --target /path/to/project --platform both
```

`--scan` is read-only inventory. `--refresh` upgrades managed files without touching locks, heartbeats, or ledger history. Existing authored text outside managed markers stays byte-for-byte unchanged.

## Feature matrix

| Feature | Claude Code | Codex | Verification |
|---|---:|---:|---|
| Explicit single/dual-platform bootstrap | Yes | Yes | Verified: platform fixtures + smoke |
| Managed lifecycle hook dispatcher | Yes | Yes | Verified: schema fixtures; live boundary below |
| Wiki, decision, failure, and workstream graphs | Yes | Yes | Verified: parser/validator fixtures |
| HEAD-only routers and root-index BFS discoverability | Yes | Yes | Verified: pass/fail graph fixtures |
| Deterministic archived history and head-consolidation proposals | Yes | Yes | Verified: hygiene fixtures; proposals never auto-mutate |
| One canonical context root shared by Git worktrees | Yes | Yes | Verified: real linked-worktree fixtures |
| Bounded task capsules and hash-backed receipts | Yes | Yes | Verified: adversarial capsule/restore fixtures |
| Mutex, append-only ledger, source claims, and agent tree | Yes | Yes | Verified: concurrency and stale-owner fixtures |
| Private global Firstmate inbox and project registry | Yes | Yes | Verified: lifecycle/privacy fixtures |
| Task readiness, human blockers, deferral, and captain disposition | Yes | Yes | Verified: task lifecycle and capsule fixtures |
| Semantic lead/balanced/economy model policy | Native Claude choice unchanged | Sol/Terra/Luna policy | Verified: catalog, fallback, conflict, rollback fixtures |
| Tagged self-extractor for one or both harnesses | Yes | Yes | Verified: clean-tag, payload, archive, checksum tests |

Verified means automated repository tests unless the compatibility page labels a dated local CLI probe. Not verified: every future Codex/Claude release, every plugin combination, remote sandbox policy, and third-party wrapper behavior. See [Codex compatibility](docs/codex-compatibility.md) for exact evidence and gaps; [contracts](docs/contracts.md) remain behavioral authority.

## What bootstrap creates

```text
AGENTS.md / CLAUDE.md            managed harness entry points
context/
├── index.html                  sole graph discoverability root
├── wiki.html + wiki/           concise durable facts
├── decisions.html + decisions/ HEAD decisions and their descendants
├── failure-todos.html + failure-todos/
├── workstreams.html + workstreams/
├── active-work.html + active-work/      dependency-aware task lifecycle
├── future-workstreams.html             deferred questions and activation triggers
├── open-questions.html + open-questions/  compatibility graph
├── control-plane.html
├── ledger-events.ndjson        append-only events and capsule receipts
├── ledger.html                 active locks/source claims
├── agent-tree.html
├── config.json
├── scripts/ and hooks/         deterministic runtime control plane
├── archived/                   absorbed source documents
└── runtime-policy.md
docs/context/                   generated human-readable projection
```

Router pages contain only graph heads. Descendants, history, and supporting detail live in linked node/files, keeping entry cost bounded. Every live page must be reachable from `context/index.html`.

## Firstmate and model roles

Global Firstmate state defaults to `${XDG_DATA_HOME:-$HOME/.local/share}/context-architecture/firstmate`; override with `CONTEXT_ARCH_FIRSTMATE`. It stores cross-project suggestions privately and exposes only registry allowlist fields to project routing.

Codex roles default to:

| Semantic role | Desired model | Effort | Direct-spawn actual |
|---|---|---:|---|
| lead (Opus-equivalent) | `gpt-5.6-sol` | high | Sol/high |
| balanced (Sonnet-equivalent) | `gpt-5.6-terra` | medium | Terra/medium |
| economy (Haiku-equivalent) | `gpt-5.6-luna` | medium | Terra/low when direct Luna override is rejected; profile discloses both |

Model discovery is fail-closed and changes only during explicit Codex `--refresh`. See [Codex compatibility](docs/codex-compatibility.md).

Task lifecycle commands are installed in each target's `context/scripts/task-lifecycle.py`.
`ready` lists dependency-satisfied tasks; `questions` lists unresolved human questions.
`new-task`, `new-question`, `answer-question`, `defer-question`, `archive-task`, and
`render` maintain linked tasks, blockers, dispositions, and routers. Readiness does
not grant permission to run work. See [task lifecycle contracts](docs/contracts.md#task-and-human-question-lifecycle)
for actor permissions, supported states, and captain confirmation.

The [zip integration report](docs/zip-integration-2026-09-26.md) records the imported
feature delta and the newer adapters retained from `codex-firstmate-overhaul`.

## Development

Core commands:

```bash
python3 scripts/bootstrap.py --target /path/to/project --scan
python3 scripts/bootstrap.py --target /path/to/project --absorb-docs --platform both
python3 scripts/bootstrap.py --target /path/to/project --refresh
python3 -m pytest -q
bash smoke.sh
scripts/release-verify.sh
```

Target-repo lifecycle commands live in generated bootloaders and [contracts](docs/contracts.md). HTML under `context/` is authoritative; Markdown under `docs/context/` is generated. Context-mode is recommended for low-context command/file/web processing, but semantic search never replaces deterministic graph validation.

Release packaging publishes one verified version directory:

```bash
./package.sh <exact-tag>
```

See the [release contract](docs/contracts.md#release-contract) for authoritative gates and artifact layout.

`context-architecture-replication-report-2026-06-05.md` is historical exploration, not current authority.
