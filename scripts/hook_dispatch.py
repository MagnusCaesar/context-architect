#!/usr/bin/env python3
"""Canonical stdin JSON hook adapter for Claude and Codex."""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


MANAGED_GROUP = "context-architecture"
CAPSULE_LIMIT = 800
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$")
MOVE_PATH = re.compile(r"^\*\*\* Move to: (.+)$")


@dataclass(frozen=True)
class Event:
    name: str
    platform: str
    cwd: Path | None
    session_id: str
    turn_id: str
    agent_id: str
    tool: str
    tool_input: dict
    paths: tuple[Path, ...]
    unsafe_paths: tuple[str, ...]
    permission_mode: str
    model: str
    prompt: str
    final_message: str


@dataclass(frozen=True)
class Result:
    allow: bool = True
    reason: str = ""
    context: str = ""
    continue_: bool = False


def block(reason: str) -> Result:
    return Result(allow=False, reason=reason)


def _payload(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _safe_path(raw: object) -> tuple[Path | None, str | None]:
    if not isinstance(raw, str) or not raw:
        return None, None
    if "\0" in raw:
        return None, "NUL path"
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        return None, raw
    return path, None


def _patch_paths(command: object) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    if not isinstance(command, str):
        return (), ()
    has_nul = "\0" in command
    started = False
    paths, unsafe = [], []
    for line in command.splitlines():
        if line == "*** Begin Patch":
            started = True
            continue
        if line == "*** End Patch":
            break
        if not started:
            continue
        matched = PATCH_PATH.match(line) or MOVE_PATH.match(line)
        if not matched:
            continue
        path, bad = _safe_path(matched.group(1))
        if bad:
            unsafe.append(bad)
        elif path and path not in paths:
            paths.append(path)
    if has_nul:
        unsafe.append("NUL payload")
    return tuple(paths), tuple(unsafe)


def normalize_event(event_name, payload) -> Event:
    """Normalize documented hook payload fields without parsing transcripts."""
    data = _payload(payload)
    tool_input = data.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    tool = str(data.get("tool_name") or data.get("tool") or "")
    platform = str(data.get("platform") or ("claude" if data.get("hook_event_name") else "codex"))
    paths: tuple[Path, ...] = ()
    unsafe: tuple[str, ...] = ()
    if tool in {"Edit", "Write"}:
        path, bad = _safe_path(tool_input.get("file_path"))
        paths = (path,) if path else ()
        unsafe = (bad,) if bad else ()
    elif tool == "apply_patch":
        paths, unsafe = _patch_paths(tool_input.get("command"))
    cwd_value = data.get("cwd")
    cwd = Path(cwd_value) if isinstance(cwd_value, str) and cwd_value else None
    return Event(
        name=str(event_name or data.get("hook_event_name") or data.get("event_name") or ""),
        platform=platform,
        cwd=cwd,
        session_id=str(data.get("session_id") or data.get("sessionId") or ""),
        turn_id=str(data.get("turn_id") or data.get("turnId") or ""),
        agent_id=str(data.get("agent_id") or data.get("agentId") or ""),
        tool=tool,
        tool_input=tool_input,
        paths=paths,
        unsafe_paths=unsafe,
        permission_mode=str(data.get("permission_mode") or data.get("permissionMode") or ""),
        model=str(data.get("model") or ""),
        prompt=str(data.get("prompt") or data.get("user_prompt") or ""),
        final_message=str(data.get("final_message") or ""),
    )


def _bounded(text: str, context_root: Path, event_name: str) -> str:
    if len(text) <= CAPSULE_LIMIT:
        return text
    diagnostics = context_root / ".hook-diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    path = diagnostics / f"{event_name or 'event'}.txt"
    path.write_text(text)
    return f"Diagnostic written: {path.relative_to(context_root)}"


def _validation_failure(context_root: Path) -> str:
    script = context_root / "scripts" / "validate.py"
    if not script.exists():
        return ""
    try:
        completed = subprocess.run(
            [sys.executable, str(script)], text=True, capture_output=True,
            cwd=context_root, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode:
        return _bounded((completed.stdout + completed.stderr).strip() or "context validation failed", context_root, "validation")
    return ""


def _freshness_update(context_root: Path) -> str:
    script = context_root / "scripts" / "check-freshness.py"
    if not script.exists():
        return ""
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--json"], text=True, capture_output=True,
            cwd=context_root, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return _bounded((completed.stdout + completed.stderr).strip(), context_root, "freshness")


def dispatch(event: Event, context_root) -> Result:
    """Run the small shared lifecycle policy; matching hooks need no ordering."""
    root = Path(context_root)
    if event.name == "PreToolUse":
        if event.unsafe_paths:
            return block("edit paths must stay inside the project")
        return Result()
    if event.name == "SessionStart":
        return Result(context=_bounded("Read context/index.html before changing tracked work.", root, event.name))
    if event.name == "UserPromptSubmit":
        if re.search(r"\b(decision|failure|open question)\b", event.prompt, re.I):
            return Result(context="Capture durable decisions, failures, or open questions in context/capture-inbox.html.")
        return Result()
    if event.name in {"PreCompact", "PostCompact"}:
        receipt = root / ".hook-receipt.json"
        receipt.write_text(json.dumps({"event": event.name, "session": event.session_id, "turn": event.turn_id}) + "\n")
        return Result(context="Context receipt recorded; restore only the current task capsule.")
    if event.name == "PostToolUse":
        if event.paths and any(p.parts and p.parts[0] == "context" for p in event.paths):
            return Result(context=_validation_failure(root))
        return Result(context=_freshness_update(root) if event.paths else "")
    if event.name == "SubagentStart":
        return Result(context=_bounded("Child scope: use the assigned task and context links only.", root, event.name))
    if event.name == "SubagentStop":
        failure = _validation_failure(root)
        return Result(context=failure, continue_=bool(failure))
    if event.name in {"Stop", "SessionEnd"}:
        receipt = root / ".hook-receipt.json"
        receipt.write_text(json.dumps({"event": event.name, "session": event.session_id, "capture": "candidate"}) + "\n")
        return Result(context="Capture any durable candidate in context/capture-inbox.html.")
    return Result()


def render_codex_result(result: Result, event_name: str) -> dict:
    output = {"hookEventName": event_name}
    if not result.allow:
        output.update(permissionDecision="deny", permissionDecisionReason=result.reason)
    elif result.context:
        output["additionalContext"] = result.context
    rendered = {"hookSpecificOutput": output}
    if result.continue_:
        rendered["continue"] = True
        rendered["reason"] = result.context
    return rendered


def render_claude_result(result: Result, event_name: str) -> dict:
    if not result.allow:
        return {"decision": "block", "reason": result.reason}
    output = {"hookEventName": event_name}
    if result.context:
        output["additionalContext"] = result.context
    return {"hookSpecificOutput": output}


def _managed(group: object) -> bool:
    return MANAGED_GROUP in json.dumps(group, sort_keys=True)


def merge_hook_config(existing, managed):
    """Replace only this named hook group; malformed configuration is untouched."""
    if isinstance(existing, (bytes, str)):
        try:
            existing = json.loads(existing)
        except (TypeError, json.JSONDecodeError):
            return existing
    if not isinstance(existing, dict):
        return existing
    merged = json.loads(json.dumps(existing))
    hooks = merged.setdefault("hooks", {})
    managed_hooks = managed.get("hooks", {}) if isinstance(managed, dict) else {}
    if not isinstance(hooks, dict) or not isinstance(managed_hooks, dict):
        return merged
    for event_name, groups in list(hooks.items()):
        if isinstance(groups, list):
            kept = [group for group in groups if not _managed(group)]
            if kept:
                hooks[event_name] = kept
            else:
                hooks.pop(event_name, None)
    for event_name, groups in managed_hooks.items():
        hooks.setdefault(event_name, []).extend(json.loads(json.dumps(groups)))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default="")
    parser.add_argument("--platform", choices=("claude", "codex"), default="codex")
    parser.add_argument("--context-root", required=True)
    parser.add_argument("--managed-group", default=MANAGED_GROUP)
    args = parser.parse_args()
    raw = sys.stdin.read()
    event = normalize_event(args.event, raw)
    result = dispatch(event, args.context_root)
    render = render_claude_result if args.platform == "claude" else render_codex_result
    print(json.dumps(render(result, event.name), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
