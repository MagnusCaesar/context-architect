# context-architect maintainer instructions

This file is for agents developing this framework repository. It is not a bootstrap template for target repos.

## Goal

Maintain a reusable Codex/Claude-compatible skill and bootstrapper that installs deterministic repo-local context architecture into other projects.

Optimize for:

- minimal edits
- low context usage
- deterministic scripts for routine checks and state changes
- HTML source of truth for generated target context pages
- clear separation between framework contracts and project payload

## Important Files

- `SKILL.md`: Codex skill entrypoint. Keep concise and valid.
- `agents/openai.yaml`: Codex UI metadata.
- `docs/contracts.md`: authoritative contracts and status schemas.
- `scripts/bootstrap.py`: creates target `context/`.
- `scripts/context_utils.py`: shared low-level helpers.
- `scripts/start-task.py`, `close-task.py`, `route-diff.py`, `check-freshness.py`, `update-tracks.py`, `validate.py`: main target-repo lifecycle tools.
- `scripts/generate-docs.py`: generated Markdown renderer normally called by close-task.
- `scripts/check-reachability.py`, `daily-hygiene.py`: orphan/broken-link hygiene.
- `scripts/record-agent.py`: advisory agent tree updates.
- `scripts/harden-ledger.sh`, `check-hardening.py`: append-only/runtime boundary checks.
- `templates/`: target repo defaults.
- `hooks/`: optional runtime hook helpers.
- `smoke.sh`: integration and contract smoke test.
- `context-architecture-replication-report-2026-06-05.md`: deprecated historical initial reference only.

## Development Rules

- Do not mutate generated target behavior casually. Update contracts, templates, scripts, and smoke coverage together.
- Keep `README.md` human-facing. Keep exact contracts in `docs/contracts.md`.
- Keep `SKILL.md` small; move detailed contract text to `docs/contracts.md`.
- Do not add semantic/LLM guessing to deterministic scripts.
- Do not make Graphify, context-mode, MCP, or hooks mandatory runtime dependencies.
- Preserve page-local `tracks`; do not move source mappings into global config.
- Ledger is events/audit only. Durable knowledge belongs in wiki/decision pages.
- New context page rule: only if no existing page owns topic, knowledge is durable, and a future read trigger exists.
- Unknown agents must remain `readonly` unless explicitly mapped in `context/config.json`.
- Use `apply_patch` for manual edits.
- Do not commit generated caches such as `__pycache__/`.

## Codex Context Discipline

Strongly prefer context-mode when developing this repo. Install and configure it
from upstream: https://github.com/mksglu/context-mode

Use context-mode tools for analysis-heavy work:

- use `ctx_batch_execute` for multi-file inventory and indexed searching
- use `ctx_execute_file` to summarize/analyze a file without loading full bytes
- use direct file reads only when exact text is needed for editing

Keep outputs bounded. Program analysis instead of manually reading large raw
outputs. context-mode is a companion retrieval/execution layer, not a substitute
for this framework's deterministic scripts or contracts.

## Validation

Run after meaningful changes:

```bash
python3 /home/vishnu_rajagopal/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
bash smoke.sh
git diff --check
```

For Python syntax-only checks:

```bash
python3 -m py_compile scripts/*.py
```

Smoke must pass before claiming the framework still works.

## Git

Keep commits scoped. Do not force-push unless explicitly asked. If remote history exists, inspect and integrate it instead of overwriting.
