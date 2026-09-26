# Context architecture zip integration

Source: `firstmate-context-architecture-skill.zip`, 74 regular files, 474,639
uncompressed bytes. SHA-256:
`6440853443cf17c18ed4fea2fff30ae37cba46be76b1626ba302c1e27f345ea2`.
The archive declares `VERSION=2098e4f-dirty`; it contains no Git history proving
that declaration.

## Comparison

| Baseline | Files | Identical shared files | Different shared files | Zip-only files | Baseline-only files |
| --- | ---: | ---: | ---: | ---: | ---: |
| Published `main`, `143f826` | 34 | 13 | 13 | 48 | 8 |
| `codex-firstmate-overhaul`, `e9e4867` | 95 | 28 | 23 | 23 | 44 |

Against published main, the archive adds 5,654 lines and removes 94 lines
(1,548 additions in shared files; 4,106 lines in new files). Baseline-only
repository metadata, documentation, licensing, and UI metadata are retained.
These are file/content comparisons, not a claim that every archive difference
is newer behavior.

The overhaul already imported `contarch-15d5dd0` at `1ce3da9` and then added
typed graphs, strict link resolution, shared worktree context, bounded capsules,
platform adapters, Firstmate privacy, model roles, and verified release tooling.
The zip's distinct addition is the Active Work / human question lifecycle.

## Integrated delta

- `task-lifecycle.py`: task creation, dependency-aware ready selection, human
  questions, answer/deferral, activation triggers, retained task disposition,
  and router maintenance.
- Bootstrap/refresh: additive lifecycle routers, archive navigation, question
  row markers, and configurable owners; authored nodes remain intact.
- Validation/capsules: stable `AW-*` and `OQ-*` IDs, lifecycle edge checks, and
  scoped agent-visible task/question context.
- Port corrections: explicit actor permissions and captain confirmation,
  safe paths/links, serialized atomic writes, and consistent router updates.
  The archive's personal `Karthik` owner is supported through configuration,
  rather than becoming a universal framework default.

## Newer behavior retained

The shared hook dispatcher replaces the zip's separate shell hooks. Its marked
hook merges retain unrelated configuration. Platform adapters replace the
single bootloader template and global-hook installer. The neutral Firstmate
data root replaces the archive's hardcoded `~/.codex/firstmate` default.
Auto-commit hooks remain retired by the overhaul's explicit policy.
Typed graph validation retains strict references rather than restoring the
zip's weaker decision aliases and supersession checks. The archive's dirty
VERSION is provenance only; exact-tag release tooling determines artifact versions.

## Verification

`scripts/release-verify.py` passed: 244 pytest cases, 101 smoke checks,
the pre-commit regression, script syntax checks, documentation contracts,
and `git diff --check`. The skill creator's `quick_validate.py` also passed.
Live Codex/Claude session probes were not run.
