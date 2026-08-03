# Codex Compatibility

This page records Codex facts and evidence boundaries. Behavioral schemas remain in [contracts](contracts.md); this page avoids duplicating them.

## Verified baseline

| Item | Evidence as of 2026-08-02 |
|---|---|
| Stable Codex CLI | `0.146.0` installed and inspected locally |
| Upstream prerelease seen | `0.147.0-alpha.4`; informative only, not a supported release claim |
| Model catalog | Local `codex app-server` `model/list`: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`; no upgrade edge in that response |
| Hook schemas | Repository Claude/Codex fixtures plus local project-hook probe |
| Subagents | Separate conversation threads; shared cwd and shared filesystem |

The 2026-08-02 fresh gate reconfirmed `codex-cli 0.146.0` and the required
`exec` flags: `--ephemeral`, `--dangerously-bypass-hook-trust`, `--sandbox
workspace-write`, `--json`, and `--color never`.

Official watch sources: [Codex changelog](https://developers.openai.com/codex/changelog/), [hooks](https://developers.openai.com/codex/hooks/), [subagents](https://developers.openai.com/codex/subagents/), [AGENTS.md](https://developers.openai.com/codex/guides/agents-md/), and [app server](https://developers.openai.com/codex/app-server/).

## Hooks and subagents

The dispatcher normalizes supported lifecycle inputs for `UserPromptSubmit`, `PreCompact`, `PostCompact`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, `Stop`, and `SessionEnd`; Claude also installs `SessionStart`. Generated project configuration is merged by managed identity, preserving unrelated user/plugin hooks and their order.

A local 2026-08-02 probe observed project hooks on subagent lifecycle and child tool calls, including `SessionStart`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `PreToolUse`, and `PostToolUse`. Stop completion was inconclusive after timeout. Treat those observations as a dated probe, not a permanent upstream guarantee.

| Event | Earlier local probe | Fresh isolated E2E |
|---|---|---|
| `SessionStart` | observed | inconclusive: run stopped at authentication |
| `UserPromptSubmit` | observed | inconclusive: run stopped at authentication |
| `SubagentStart` / `SubagentStop` | observed | inconclusive: no model turn ran |
| parent/child `PreToolUse` / `PostToolUse` | observed | inconclusive: no model turn ran |
| `Stop` / `SessionEnd` | not captured in bounded run | inconclusive |

The fresh harness used temporary project hooks and temporary writable
`HOME`/`CODEX_HOME` plus a minimal bubblewrap root containing system runtime
directories, the exact Node/Codex installation, the temporary project, and
read-only `auth.json`/`config.toml` mounts. It does not bind `/`; a sentinel
proves every other host `~/.codex` path is inaccessible. Credentials are never
copied. Both API-key environment variables were absent, and the isolated run
was rejected by the Responses websocket with HTTP 401. The harness records
allowlisted schema keys only, redacts unknown key names, rejects any non-JSON
stdout even beside `turn.completed`, and uses a Python stdlib process-group
timeout. Writable `~/.codex` was not used.

Subagent context isolation means a separate conversation thread, not a separate machine or checkout. Subagents still receive applicable system/project instructions. They share cwd and filesystem unless the orchestrator deliberately assigns a worktree. Therefore:

- Context contents are isolated by thread.
- File mutations are shared and can race.
- Project hooks/instructions were inherited in the dated local probe.
- Use the framework mutex/source claims or separate Git worktrees for concurrent writers.

The generated agent capsule contains task, expected result, scope, and only relevant fact/decision/blocker nodes. Graph schema, mutex internals, hygiene, receipts, registry archives, and control-plane narration stay script-owned.

## Model policy

| Role | Desired catalog model | Desired effort | Current direct-spawn behavior |
|---|---|---:|---|
| lead / Opus-equivalent | `gpt-5.6-sol` | high | Sol/high |
| balanced / Sonnet-equivalent | `gpt-5.6-terra` | medium | Terra/medium |
| economy / Haiku-equivalent | `gpt-5.6-luna` | medium | Current direct override rejects Luna; use Terra/low and disclose desired + actual |

Catalog discovery uses the app-server JSON-RPC sequence `initialize` → `initialized` → paginated `model/list`. Validation rejects missing fields, duplicate/ambiguous models, hidden targets, unsupported efforts, malformed upgrade metadata, timeouts, and conflicting on-disk profiles.

Policy updates happen only on explicit refresh:

```bash
python3 context/scripts/bootstrap.py --target /path/to/project --refresh
```

For Codex projects, that explicit refresh queries the catalog. A role changes only when the current model advertises one unique, visible, valid upgrade target. No refresh means no model change. Failed or ambiguous refresh preserves the prior policy and profiles atomically. Claude-only refresh never installs Codex model policy.

## Verified versus not verified

Automated fixtures verify event normalization, managed config merge, edit/lock gates, bounded diagnostics, capsule privacy, Firstmate privacy, model pagination/fallback/rollback, and platform-specific bootstrap. Real linked-worktree tests verify canonical shared state and copied/malformed locator rejection.

Fresh 2026-08-02 results: `232` pytest tests passed; `101` smoke checks passed;
all Python scripts compiled; `7` shell hook/test/script files passed `bash -n`;
the linked-worktree lifecycle E2E passed; and deterministic hook adversaries
passed. Those adversaries cover unrelated-hook preservation, multi-file
unowned-path denial, malformed-edit fail-closed behavior, bounded diagnostic
spill, race-safe one-time child continuation on validation failure, bounded
capsule privacy, corrupt-catalog rollback, hostile Git configuration/hooks,
portable timeout behavior, real history mutation, and the generated
Luna-to-Terra/low fallback.
Manual Claude Code E2E was outside this Codex-only gate and was not run.

Not verified as a durable guarantee:

- Future Codex hook names or payload fields not present in fixtures.
- Hook inheritance behavior after later CLI releases.
- Direct Luna override support after later model releases.
- Actual economy child execution in the fresh E2E; isolated authentication failed before a model turn, so only generated-profile fallback was verified.
- Remote sandbox, MCP/plugin, IDE, or wrapper-specific policies.
- `Stop` and `SessionEnd` in a completed live run.

When upstream changes, add/update a failing fixture first, adapt the normalizer or model policy once, then update this dated baseline. Do not auto-update behavior during ordinary sessions.
