#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/contarch-codex-hooks.XXXXXX")
cleanup() {
  if [ "${CONTARCH_KEEP_TMP:-0}" = 1 ]; then
    echo "diagnostic workspace: $TMP"
  else
    rm -rf "$TMP"
  fi
}
trap cleanup EXIT
PROJECT="$TMP/project"
STATE="$TMP/codex-home"
LOG="$PROJECT/hook-schema.ndjson"
mkdir -p "$PROJECT/.codex" "$STATE"

git -C "$PROJECT" init -b main >/dev/null
git -C "$PROJECT" config user.email e2e@example.invalid
git -C "$PROJECT" config user.name "contarch e2e"
git -C "$PROJECT" commit --allow-empty -m base >/dev/null

cat >"$PROJECT/sanitize-hook.py" <<'PY'
#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

event = sys.argv[1]
log = Path(sys.argv[2])
try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    payload = {}
payload = payload if isinstance(payload, dict) else {}
tool_input = payload.get("tool_input")
tool_input = tool_input if isinstance(tool_input, dict) else {}
tool = payload.get("tool_name") or payload.get("tool") or ""
tool = tool if tool in {"Bash", "apply_patch", "Edit", "Write", "Read"} else "other"
model = payload.get("model") or ""
model = model if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model) else ""
record = {
    "event": event,
    "keys": sorted(str(key) for key in payload),
    "tool_input_keys": sorted(str(key) for key in tool_input),
    "tool": tool,
    "child": bool(payload.get("agent_id") or payload.get("agentId")),
    "model": model,
}
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
print(json.dumps({"hookSpecificOutput": {"hookEventName": event}}, separators=(",", ":")))
PY
chmod +x "$PROJECT/sanitize-hook.py"

cat >"$PROJECT/sanitize-codex-stream.py" <<'PY'
#!/usr/bin/env python3
import collections
import json
import sys
from pathlib import Path

counts = collections.Counter()
invalid = 0
for line in sys.stdin:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        invalid += 1
        continue
    if isinstance(payload, dict):
        counts[str(payload.get("type") or "unknown")] += 1
Path(sys.argv[1]).write_text(json.dumps({"events": counts, "invalid": invalid}, sort_keys=True) + "\n")
PY
chmod +x "$PROJECT/sanitize-codex-stream.py"

PROJECT="$PROJECT" LOG="$LOG" python3 - <<'PY'
import json
import os
import shlex
from pathlib import Path

project = Path(os.environ["PROJECT"])
log = Path(os.environ["LOG"])
command = f"python3 {shlex.quote(str(project / 'sanitize-hook.py'))} __EVENT__ {shlex.quote(str(log))}"
events = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop", "Stop", "SessionEnd")
hooks = {}
for event in events:
    group = {"hooks": [{"type": "command", "command": command.replace("__EVENT__", event), "marker": "e2e-unrelated"}]}
    hooks[event] = [group]
(project / ".codex/hooks.json").write_text(json.dumps({"hooks": hooks}, indent=2) + "\n")
PY

python3 "$ROOT/scripts/bootstrap.py" --target "$PROJECT" --platform codex >/dev/null

ROOT="$ROOT" PROJECT="$PROJECT" python3 - <<'PY'
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["ROOT"])
project = Path(os.environ["PROJECT"])
context = project / "context"
dispatcher = context / "scripts/hook_dispatch.py"

configured = json.loads((project / ".codex/hooks.json").read_text())
assert "e2e-unrelated" in json.dumps(configured)
assert "hook_dispatch.py" in json.dumps(configured)
economy = (project / ".codex/agents/economy.toml").read_text()
assert 'model = "gpt-5.6-terra"' in economy
assert 'model_reasoning_effort = "low"' in economy
assert "Desired gpt-5.6-luna/medium; actual gpt-5.6-terra/low" in economy

def dispatch(event, payload):
    completed = subprocess.run(
        [sys.executable, str(dispatcher), "--platform", "codex", "--event", event,
         "--context-root", str(context)],
        input=json.dumps(payload), capture_output=True, text=True, check=True,
    )
    return json.loads(completed.stdout)

outside = project.parent / "unowned.py"
multi = dispatch("PreToolUse", {
    "cwd": str(project), "tool_name": "apply_patch",
    "tool_input": {"command": "*** Begin Patch\n*** Add File: owned.py\n+x\n*** Add File: ../unowned.py\n+x\n*** End Patch"},
})
assert multi["hookSpecificOutput"]["permissionDecision"] == "deny"
malformed = dispatch("PreToolUse", {"cwd": str(project), "tool_name": "Write", "tool_input": {}})
assert malformed["hookSpecificOutput"]["permissionDecision"] == "deny"
capsule = dispatch("SubagentStart", {
    "cwd": str(project), "agent_id": "child", "task": "Inspect cache boundaries",
    "expected_result": "Report one bounded finding", "scope": ["src/cache.py"],
})["hookSpecificOutput"]["additionalContext"]
assert len(capsule) <= 4000 and "Inspect cache boundaries" in capsule
for hidden in ("ledger-events.ndjson", "receipt_id", "mutex", "hygiene", "project-registry", "archive"):
    assert hidden not in capsule

validator = context / "scripts/validate.py"
original = validator.read_bytes()
validator.write_text("import sys\nprint('X' * 2400)\nsys.exit(1)\n")
post = dispatch("PostToolUse", {
    "cwd": str(project), "tool_name": "Write",
    "tool_input": {"file_path": "context/wiki.html"},
})
message = post["hookSpecificOutput"]["additionalContext"]
assert message.startswith("Diagnostic written: ")
spill = context / message.removeprefix("Diagnostic written: ")
assert spill.is_file() and spill.stat().st_size > 800
first_stop = dispatch("SubagentStop", {"cwd": str(project), "agent_id": "child"})
assert first_stop.get("continue") is True
validator.write_bytes(original)
second_stop = dispatch("SubagentStop", {"cwd": str(project), "agent_id": "child"})
assert "continue" not in second_stop

profiles = sorted((project / ".codex/agents").glob("*.toml"))
before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in profiles}
fake = project.parent / "fake-bin"
fake.mkdir()
server = fake / "codex"
server.write_text("#!/usr/bin/env sh\nprintf '{broken\\n'\n")
server.chmod(0o755)
env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ["PATH"])
refreshed = subprocess.run(
    [sys.executable, str(root / "scripts/bootstrap.py"), "--target", str(project), "--refresh"],
    env=env, capture_output=True, text=True,
)
assert refreshed.returncode == 0, refreshed.stderr
after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in profiles}
assert before == after
print("deterministic hook adversaries: PASS")
PY

if [ "${CONTARCH_LIVE_CODEX:-1}" = 0 ]; then
  echo "live Codex hooks: SKIP (CONTARCH_LIVE_CODEX=0)"
  exit 0
fi
if ! command -v codex >/dev/null 2>&1; then
  echo "live Codex hooks: SKIP (codex executable unavailable)"
  exit 0
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
  LIVE=(env CODEX_HOME="$STATE")
elif command -v bwrap >/dev/null 2>&1 && [ -f "$HOME/.codex/auth.json" ]; then
  touch "$STATE/auth.json"
  CONFIG_BIND=()
  if [ -f "$HOME/.codex/config.toml" ]; then
    touch "$STATE/config.toml"
    CONFIG_BIND=(--ro-bind "$HOME/.codex/config.toml" "$STATE/config.toml")
  fi
  LIVE=(bwrap --ro-bind / / --dev-bind /dev /dev --proc /proc --bind "$TMP" "$TMP"
        --ro-bind "$HOME/.codex/auth.json" "$STATE/auth.json" "${CONFIG_BIND[@]}"
        --setenv CODEX_HOME "$STATE"
        --chdir "$PROJECT")
else
  echo "live Codex hooks: SKIP (no isolated credential path; global state left untouched)"
  exit 0
fi

PROMPT='Lifecycle test. Use Bash once to create parent-bash.txt. Use apply_patch once to add parent-patch.txt. Spawn exactly one economy subagent; tell it to use Bash once and apply_patch once to create child-bash.txt and child-patch.txt, then wait for it. Do not inspect hook logs, transcripts, or global files. End with done.'
set +e
timeout "${CONTARCH_CODEX_TIMEOUT:-240}s" "${LIVE[@]}" codex exec --ephemeral \
  --dangerously-bypass-hook-trust --sandbox workspace-write --json --color never \
  -C "$PROJECT" "$PROMPT" 2>"$TMP/codex-stderr" \
  | python3 "$PROJECT/sanitize-codex-stream.py" "$TMP/codex-stream-status.json"
PIPE_STATUS=("${PIPESTATUS[@]}")
LIVE_STATUS=${PIPE_STATUS[0]}
STREAM_STATUS=${PIPE_STATUS[1]}
set -e

LOG="$LOG" LIVE_STATUS="$LIVE_STATUS" STREAM_STATUS="$STREAM_STATUS" python3 - <<'PY'
import collections
import json
import os
import re
from pathlib import Path

status = int(os.environ["LIVE_STATUS"])
log = Path(os.environ["LOG"])
assert int(os.environ["STREAM_STATUS"]) == 0, "Codex JSON stream sanitizer failed"
stream = json.loads((log.parents[1] / "codex-stream-status.json").read_text())
if status:
    stderr = (log.parents[1] / "codex-stderr").read_text(errors="replace")
    if "401 Unauthorized" in stderr:
        print("live Codex hooks: INCONCLUSIVE (isolated read-only auth rejected with HTTP 401; global state untouched)")
        raise SystemExit(0)
    categories = [name for name, pattern in {
        "auth": r"(?i)auth|login|credential",
        "config": r"(?i)config|toml|json",
        "hook": r"(?i)hook",
        "model": r"(?i)model",
        "network": r"(?i)network|connect|dns|http",
        "read-only": r"(?i)read.?only|permission denied",
        "sqlite": r"(?i)sqlite|database",
        "timeout": r"(?i)timeout|timed out",
    }.items() if re.search(pattern, stderr)]
    raise AssertionError(f"codex exec failed with status {status}; categories={','.join(categories) or 'unknown'}")
assert stream["events"].get("turn.completed", 0) == 1, f"Codex stream did not complete: {stream['events']}"
assert not any("fail" in name or "error" in name for name in stream["events"]), stream["events"]
rows = [json.loads(line) for line in log.read_text().splitlines() if line]
events = collections.Counter(row["event"] for row in rows)
required = {"SessionStart", "UserPromptSubmit", "SubagentStart", "SubagentStop", "PreToolUse", "PostToolUse"}
missing = sorted(required - events.keys())
assert not missing, f"missing live hook events: {', '.join(missing)}"
for child in (False, True):
    for event in ("PreToolUse", "PostToolUse"):
        for tool in ("Bash", "apply_patch"):
            assert any(row["event"] == event and row["child"] is child and row["tool"] == tool for row in rows), (child, event, tool)

economy = log.parent / ".codex/agents/economy.toml"
expected = next(line.split("=", 1)[1].strip().strip('"') for line in economy.read_text().splitlines() if line.startswith("model ="))
child_models = {row["model"] for row in rows if row["event"] == "SubagentStart" and row["model"]}
assert expected in child_models, f"economy profile selected {expected}, observed {sorted(child_models)}"
terminal = {name: ("pass" if events[name] else "inconclusive") for name in ("Stop", "SessionEnd")}
matrix = ", ".join(f"{name}={events[name]}" for name in sorted(events))
print(f"live Codex hooks: PASS ({matrix}; Stop={terminal['Stop']}; SessionEnd={terminal['SessionEnd']}; economy={expected})")
PY
