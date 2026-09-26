---
name: context-architecture
description: "Bootstrap and operate deterministic repo-local context architecture for Codex/Claude-style agent work: map-first context wiki, locks, ledgers, agent tree, decision graph, freshness routing, validation, and low-context multi-agent coordination."
metadata:
  context_architecture:
    contract_version: 1
    default_role: worker
    permission_profiles: templates/permission-profiles.json
---

Use when:

- The user wants persistent project context, agent memory architecture, or multi-agent coordination.
- A project needs a context wiki, decision/failure/work graph, ledger, locks, or deterministic hygiene.
- Invoke once per target directory. Generated `AGENTS.md`/`CLAUDE.md` own routine work afterward.

## Authority

`docs/contracts.md` is the behavioral authority. Read only the relevant section
before changing or explaining a contract. `docs/codex-compatibility.md` records
version-specific observations, not normative behavior.

North star: scripts own ritual; models own judgment. Keep control-plane hygiene
out of model context. Use one canonical context root across Git worktrees. Hooks
are optional until installed and verified in the active runtime.

## Run

Set `SKILL_DIR` to the directory containing this file. If the user says “this
repo” without a target, use the current working directory.

### Inspect, then bootstrap

```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --scan
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --platform codex
```

Use `--platform claude` or `--platform both` when requested or detected
unambiguously. `--scan` is read-only. Bootstrap creates the context skeleton,
managed bootloader blocks, hooks, and profiles. Resolve reported ambiguities;
do not guess.

Existing docs are imported only on explicit request:

```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --absorb-docs
```

### Refresh

```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --target /path/to/project --refresh
```

Refresh updates skill-owned machinery and preserves authored pages, ledger,
locks, and existing configuration values. For Codex, only explicit refresh may
query `codex app-server` for model upgrades; failure preserves the installed
policy bundle.

### Global Firstmate

```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --scope global --platform both
```

The neutral data root and privacy/migration rules are in `docs/contracts.md`.
Use `--init-git` only when requested. Migrate by copy, never by deletion:

```bash
python3 "$SKILL_DIR/scripts/bootstrap.py" --scope global \
  --migrate-firstmate /legacy/root
```

## Verify

After framework changes:

```bash
python3 /path/to/project/context/scripts/validate.py
bash "$SKILL_DIR/smoke.sh"
```

Run deterministic scripts when permissions allow; do not merely describe them.
Keep writes surgical. Do not add semantic guessing, mandatory services, or
project-specific payload to the framework.

For cheap reads, use `context/scripts/extract-body.py` on context HTML. Prefer
context-mode for other analysis when available; it remains a companion, not a
runtime dependency or contract authority.

For dependency-aware task selection, human blockers, deferral, and task
disposition, use the installed `context/scripts/task-lifecycle.py`. Read only
the [task lifecycle contract](docs/contracts.md#task-and-human-question-lifecycle)
when operating or changing that workflow. Task readiness never authorizes execution.
