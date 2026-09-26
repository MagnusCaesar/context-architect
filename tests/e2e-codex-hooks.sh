#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
HOST_HOME=$HOME
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
HOME="$TMP/home"
export HOME GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
mkdir -p "$PROJECT/.codex" "$STATE" "$HOME/hostile-hooks"
cat >"$HOME/.gitconfig" <<EOF
[commit]
    gpgSign = true
[core]
    hooksPath = $HOME/hostile-hooks
EOF
printf '#!/bin/sh\nexit 99\n' >"$HOME/hostile-hooks/pre-commit"
chmod +x "$HOME/hostile-hooks/pre-commit"

git -C "$PROJECT" init -b main >/dev/null
git -C "$PROJECT" config --local user.email e2e@example.invalid
git -C "$PROJECT" config --local user.name "contarch e2e"
git -C "$PROJECT" config --local commit.gpgSign false
git -C "$PROJECT" config --local core.hooksPath /dev/null
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
known_payload = {
    "agent_id", "agentId", "agent_type", "cwd", "event_name", "expected_result",
    "hook_event_name", "last_assistant_message", "model", "permission_mode", "prompt",
    "result", "role", "scope", "session_id", "sessionId", "task", "tool", "tool_input",
    "tool_name", "turn_id", "turnId",
}
known_tool_input = {"command", "file_path", "links", "path", "result", "scope", "task"}
record = {
    "event": event,
    "keys": sorted(key for key in payload if key in known_payload),
    "tool_input_keys": sorted(key for key in tool_input if key in known_tool_input),
    "unknown_keys": {"count": sum(key not in known_payload for key in payload), "names": "redacted"},
    "unknown_tool_input_keys": {"count": sum(key not in known_tool_input for key in tool_input), "names": "redacted"},
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
raise SystemExit(1 if invalid else 0)
PY
chmod +x "$PROJECT/sanitize-codex-stream.py"

cat >"$PROJECT/run-with-timeout.py" <<'PY'
#!/usr/bin/env python3
import os
import signal
import subprocess
import sys

seconds = float(sys.argv[1])
process = subprocess.Popen(sys.argv[2:], start_new_session=True)
try:
    raise SystemExit(process.wait(timeout=seconds))
except subprocess.TimeoutExpired:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()
    raise SystemExit(124)
PY
chmod +x "$PROJECT/run-with-timeout.py"

cat >"$PROJECT/timeout-tree.py" <<'PY'
import os
import signal
import subprocess
import sys
import time

marker = sys.argv[1]
level = int(sys.argv[2]) if len(sys.argv) > 2 else 0
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if level < 2:
    subprocess.Popen([sys.executable, __file__, marker, str(level + 1)])
time.sleep(1)
open(marker, "w").close()
PY

printf '%s\n' '{"type":"turn.completed"}' 'not-json' \
  | if python3 "$PROJECT/sanitize-codex-stream.py" "$TMP/invalid-stream.json"; then
      echo "invalid Codex stream was accepted" >&2
      exit 1
    fi
printf '%s\n' '{"api_secret_name":"hidden","tool_input":{"password_field":"hidden"}}' \
  | python3 "$PROJECT/sanitize-hook.py" SecretProbe "$TMP/sanitizer-test.ndjson" >/dev/null
SANITIZER_TEST="$TMP/sanitizer-test.ndjson" python3 - <<'PY'
import json
import os
from pathlib import Path

text = Path(os.environ["SANITIZER_TEST"]).read_text()
assert "api_secret_name" not in text and "password_field" not in text
record = json.loads(text)
assert record["unknown_keys"] == {"count": 1, "names": "redacted"}
assert record["unknown_tool_input_keys"] == {"count": 1, "names": "redacted"}
PY
PYTHON_BIN=$(command -v python3)
set +e
PATH="$TMP/no-timeout" "$PYTHON_BIN" "$PROJECT/run-with-timeout.py" 0.05 \
  "$PYTHON_BIN" -c 'import time; time.sleep(5)'
TIMEOUT_STATUS=$?
set -e
[ "$TIMEOUT_STATUS" -eq 124 ]

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
assert 'model = "gpt-6-luna"' in economy
assert 'model_reasoning_effort = "medium"' in economy
assert "Desired gpt-6-luna/medium; actual gpt-6-luna/medium" in economy

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
second_stop = dispatch("SubagentStop", {"cwd": str(project), "agent_id": "child"})
assert "continue" not in second_stop
assert subprocess.run(
    ["git", "check-ignore", "-q", "context/.hook-state/subagent-stop.json"], cwd=project
).returncode == 0
validator.write_bytes(original)
repaired_stop = dispatch("SubagentStop", {"cwd": str(project), "agent_id": "child"})
assert "continue" not in repaired_stop

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

if ! command -v bwrap >/dev/null 2>&1; then
  echo "timeout descendant cleanup: SKIP (bubblewrap unavailable)"
else
  RUNTIME_BINDS=()
  for source in /usr /bin /lib /lib64 /etc/alternatives /etc/crypto-policies /etc/pki /etc/ssl /etc/resolv.conf /etc/hosts /etc/nsswitch.conf /etc/passwd /etc/group; do
    [ ! -e "$source" ] || RUNTIME_BINDS+=(--ro-bind "$source" "$source")
  done
  TREE_LIVE=(bwrap --die-with-parent "${RUNTIME_BINDS[@]}"
             --proc /proc --dev /dev --dir /tmp --bind "$TMP" "$TMP" --chdir "$PROJECT")
  TREE_MARKER="$TMP/timeout-tree-survived"
  set +e
  "$PYTHON_BIN" "$PROJECT/run-with-timeout.py" 0.1 \
    "${TREE_LIVE[@]}" /usr/bin/python3 "$PROJECT/timeout-tree.py" "$TREE_MARKER"
  TREE_STATUS=$?
  set -e
  [ "$TREE_STATUS" -eq 124 ]
  sleep 1.1
  [ ! -e "$TREE_MARKER" ]
  echo "timeout descendant cleanup: PASS"
fi

if [ "${CONTARCH_LIVE_CODEX:-1}" = 0 ]; then
  echo "live Codex hooks: SKIP (CONTARCH_LIVE_CODEX=0)"
  exit 0
fi
if ! command -v codex >/dev/null 2>&1; then
  echo "live Codex hooks: SKIP (codex executable unavailable)"
  exit 0
fi
if ! command -v bwrap >/dev/null 2>&1; then
  echo "live Codex hooks: SKIP (bubblewrap unavailable; host data remains hidden)"
  exit 0
fi

AUTH_BIND=()
if [ -n "${OPENAI_API_KEY:-}" ]; then
  : # API key stays in the inherited environment; HOME and CODEX_HOME are temporary.
elif [ -f "$HOST_HOME/.codex/auth.json" ]; then
  touch "$STATE/auth.json"
  AUTH_BIND=(--ro-bind "$HOST_HOME/.codex/auth.json" "$STATE/auth.json")
  if [ -f "$HOST_HOME/.codex/config.toml" ]; then
    touch "$STATE/config.toml"
    AUTH_BIND+=(--ro-bind "$HOST_HOME/.codex/config.toml" "$STATE/config.toml")
  fi
else
  echo "live Codex hooks: SKIP (no isolated credential path; global state left untouched)"
  exit 0
fi

NODE_BIN=$(readlink -f "$(command -v node)")
CODEX_ENTRY=$(readlink -f "$(command -v codex)")
case "$CODEX_ENTRY" in
  */bin/codex.js) CODEX_SCOPE=${CODEX_ENTRY%/codex/bin/codex.js} ;;
  *) echo "live Codex hooks: SKIP (unrecognized Codex installation; host data remains hidden)"; exit 0 ;;
esac
LIVE=(bwrap --die-with-parent "${RUNTIME_BINDS[@]}"
      --ro-bind "$NODE_BIN" "$NODE_BIN" --ro-bind "$CODEX_SCOPE" "$CODEX_SCOPE"
      --proc /proc --dev /dev --dir /tmp --bind "$TMP" "$TMP" "${AUTH_BIND[@]}"
      --setenv HOME "$HOME" --setenv CODEX_HOME "$STATE" --chdir "$PROJECT")
CONTARCH_HOST_SENTINEL="$HOST_HOME/.codex/AGENTS.md" "${LIVE[@]}" /usr/bin/python3 - <<'PY'
import os
from pathlib import Path

assert not Path(os.environ["CONTARCH_HOST_SENTINEL"]).exists()
PY

PROMPT='Lifecycle test. You MUST call the spawn_agent tool exactly once and select the economy custom agent. Its read-only task MUST use Bash once to run git status --short and Read once to inspect AGENTS.md. After spawning, wait for that child to finish. In the parent, use Bash once to create parent-bash.txt and apply_patch once to add parent-patch.txt. Do not inspect hook logs, transcripts, or global files. A prose-only delegation is failure. End with done.'
set +e
"$PYTHON_BIN" "$PROJECT/run-with-timeout.py" "${CONTARCH_CODEX_TIMEOUT:-240}" \
  "${LIVE[@]}" "$NODE_BIN" "$CODEX_ENTRY" exec \
  --enable multi_agent -c agents.enabled=true \
  --dangerously-bypass-hook-trust --sandbox workspace-write --json --color never \
  -C "$PROJECT" "$PROMPT" 2>"$TMP/codex-stderr" \
  | python3 "$PROJECT/sanitize-codex-stream.py" "$TMP/codex-stream-status.json"
PIPE_STATUS=("${PIPESTATUS[@]}")
LIVE_STATUS=${PIPE_STATUS[0]}
STREAM_STATUS=${PIPE_STATUS[1]}
set -e

LOG="$LOG" LIVE_STATUS="$LIVE_STATUS" STREAM_STATUS="$STREAM_STATUS" \
  LIVE_STRICT="${CONTARCH_LIVE_STRICT:-0}" python3 - <<'PY'
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
parent_required = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
parent_missing = sorted(parent_required - events.keys())
assert not parent_missing, "missing live parent hook events: " + ", ".join(parent_missing)
child_required = {"SubagentStart", "SubagentStop"}
child_missing = sorted(child_required - events.keys())
if set(child_missing) == child_required:
    message = "successful parent did not exercise spawn_agent; no subagent lifecycle claim"
    if os.environ["LIVE_STRICT"] == "1":
        raise AssertionError("live Codex hooks: FAIL (" + message + ")")
    print("live Codex hooks: INCONCLUSIVE (" + message + ")")
    raise SystemExit(0)
assert not child_missing, "incomplete live subagent lifecycle: " + ", ".join(child_missing)
tools = {False: ("Bash", "apply_patch"), True: ("Bash", "Read")}
for child, expected_tools in tools.items():
    for event in ("PreToolUse", "PostToolUse"):
        for tool in expected_tools:
            assert any(row["event"] == event and row["child"] is child and row["tool"] == tool for row in rows), (child, event, tool)

economy = log.parent / ".codex/agents/economy.toml"
expected = next(line.split("=", 1)[1].strip().strip('"') for line in economy.read_text().splitlines() if line.startswith("model ="))
child_models = {row["model"] for row in rows if row["event"] == "SubagentStart" and row["model"]}
assert expected in child_models, f"economy profile selected {expected}, observed {sorted(child_models)}"
terminal = {name: ("pass" if events[name] else "inconclusive") for name in ("Stop", "SessionEnd")}
matrix = ", ".join(f"{name}={events[name]}" for name in sorted(events))
print(f"live Codex hooks: PASS ({matrix}; Stop={terminal['Stop']}; SessionEnd={terminal['SessionEnd']}; economy={expected})")
PY
