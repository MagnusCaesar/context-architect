# Task 7 report

- Added explicit Claude/Codex platform resolution, managed instruction rendering, byte-preserving marker upsert, and stored refresh selection.
- `--platform claude|codex|both` controls bootstrap and installer dry runs; refresh uses `context/config.json` without redetection and reports a required new session.
- Replaced the shared bootloader template with common, Claude, and Codex templates. Claude/Codex outputs exclude the other harness vocabulary.
- Preserved Claude hook behavior only when Claude is selected; no Task 8 dispatcher or Firstmate work added.

Verification: focused adapter pytest (16), full pytest (53), smoke (90), Python/shell syntax, skill validation, and `git diff --check` passed.

Self-review: no remaining in-scope concern. `package.sh` was adjusted only so a deleted tracked template does not break a working-tree installer build.

## Review fix round 1: RED/GREEN evidence

- RED: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_platform_adapters.py` — 7 failed, 13 passed. Failures reproduced implicit installer dual selection, dry-run temp staging, sequential dual-target writes, and bootstrap/refresh mutation before marker validation.
- GREEN: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_platform_adapters.py` — 20 passed.
- Final verification: full pytest 57 passed; smoke 96 passed; `git diff --check` passed.
