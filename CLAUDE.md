# context-architect Claude maintainer instructions

This file is for Claude Code or Claude-style agents developing this framework repository. It is not copied into target repos by bootstrap.

## Goal

Maintain a reusable skill/bootstrap system that installs deterministic repo-local context architecture into other projects.

The framework should reduce agent context usage and make routine coordination enforceable through scripts. Agents interpret meaning; scripts handle locks, ledgers, routing, validation, freshness, reachability, docs rendering, and advisory agent-tree updates.

## Source Of Truth

- `SKILL.md`: skill entrypoint and core workflow.
- `docs/contracts.md`: authoritative contracts and status schemas.
- `scripts/`: deterministic implementation.
- `templates/`: files copied into target repos.
- `hooks/`: optional hook helpers.
- `smoke.sh`: lifecycle verification.
- `README.md`: public human guide.
- `context-architecture-replication-report-2026-06-05.md`: deprecated historical initial reference only.

## Development Constraints

- Prefer minimal edits.
- Keep deterministic behavior in scripts, not prompts.
- Keep framework contracts separate from project payload.
- Do not make hooks mandatory; verify hook payloads before relying on them.
- Do not make Graphify, context-mode, or MCP mandatory.
- Do not let ledger become durable memory. Ledger is event audit; wiki/decision pages hold durable knowledge.
- Do not allow missing `tracks` to imply scanning the whole repo.
- Do not weaken unknown-agent default role from `readonly`.
- Update smoke coverage when changing script contracts.

## Claude Code Notes

Hooks under `hooks/` are optional helpers for target repos. Treat them as untrusted until tested against the actual Claude Code hook invocation shape.

If maintaining this repository from Claude Code, use the framework's scripts directly and keep outputs concise. Do not paste large generated reports into chat. Summarize with file paths and validation results.

## Validation

Run:

```bash
python /home/vishnu_rajagopal/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
bash smoke.sh
git diff --check
```

Syntax-only check:

```bash
python3 -m py_compile scripts/*.py
```

Smoke covers bootstrap, locking, stale lock break, routing, freshness, track repair, reachability/hygiene, decisions, close-task validation warning, and docs generation.

## Git

Keep commits narrow and descriptive. Do not overwrite unrelated user work. Do not force-push unless explicitly instructed.
