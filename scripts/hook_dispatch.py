#!/usr/bin/env python3
"""Canonical stdin JSON hook adapter for Claude and Codex."""

import argparse
import fnmatch
import hashlib
import json
import math
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from context_utils import read_config, read_meta, registered_projects, tracks_status


MANAGED_GROUP = "context-architecture"
CAPSULE_LIMIT = 800
RECEIPT_LIMIT = 65536
RECEIPT_MAX_AGE = 3600
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$")
MOVE_PATH = re.compile(r"^\*\*\* Move to: (.+)$")
SECRET = re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+")
LEGACY_HOOK_NAMES = frozenset({
    "auto-commit-context.sh", "capture-on-stop.sh", "post-edit-validate-and-stale.sh",
    "post-edit-validate.sh", "post-read-context-gate.sh", "pre-edit-context-gate.sh",
    "pre-edit-context-inject.sh", "pre-edit-lock-check.sh", "remind-capture-decision.sh",
    "remind-context-read.sh", "session-start-inject.sh", "subagent-start-inject.sh",
})
READ_ONLY_PARTS = frozenset({"input_rpts", "processed", "logs"})


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
    role: str
    task: str
    scope: tuple[str, ...]


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


def _clean(value: object, limit: int = 240) -> str:
    if not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value):
        return ""
    text = " ".join(str(value or "").split())
    text = SECRET.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    return text[:limit]


def _scope(value: object) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else [value]
    return tuple(clean for clean in (_clean(item, 160) for item in values[:8]) if clean)


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
    if tool in {"Edit", "Write", "Read"}:
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
        role=_clean(data.get("agent_type") or data.get("role") or tool_input.get("agent_type") or tool_input.get("role")),
        task=_clean(data.get("task") or data.get("task_name") or tool_input.get("task_name") or tool_input.get("message")),
        scope=_scope(data.get("scope") or tool_input.get("scope") or ()),
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


def _receipt_path(context_root: Path, session_id: str) -> Path:
    key = hashlib.sha256((session_id or "anonymous").encode()).hexdigest()[:20]
    return context_root / ".hook-receipts" / f"{key}.json"


def _capsule(event: Event) -> str:
    fields = [
        f"agent={_clean(event.agent_id, 120)}" if event.agent_id else "",
        f"role={event.role}" if event.role else "",
        f"task={event.task}" if event.task else "",
        f"scope={', '.join(event.scope)}" if event.scope else "",
    ]
    content = "; ".join(field for field in fields if field)
    return f"Child context: {content}" if content else ""


def _firstmate_state(context_root: Path):
    if read_config(context_root).get("scope") != "global":
        return None
    status = "unknown"
    state = context_root / ".validation-state.json"
    try:
        if state.stat().st_size <= 16_384:
            data = json.loads(state.read_text())
            if isinstance(data, dict):
                status = _clean(data.get("status"), 40) or status
    except (OSError, json.JSONDecodeError):
        pass
    return registered_projects(context_root), status


def _firstmate_route(context_root: Path, text: str) -> str:
    state = _firstmate_state(context_root)
    if not state or not text:
        return ""
    projects, _ = state
    matched = []
    for name, path, _summary, status in projects:
        named = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I)
        if named or path in text:
            matched.append((name, path, status))
    if len(matched) != 1:
        return ""
    name, path, status = matched[0]
    return f"Firstmate route: project={_clean(name, 80)}; root={_clean(path, 500)}; status={_clean(status, 40) or 'unknown'}"


def _record_receipt(event: Event, context_root: Path) -> None:
    path = _receipt_path(context_root, event.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({
        "created_at": time.time(), "session": event.session_id, "turn": event.turn_id,
        "capsule": _capsule(event),
    }, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(data)
        staged = Path(handle.name)
    staged.replace(path)


def _restore_receipt(event: Event, context_root: Path) -> str:
    path = _receipt_path(context_root, event.session_id)
    if not path.exists():
        return ""
    if path.stat().st_size > RECEIPT_LIMIT:
        return "Compaction receipt ignored: oversized."
    try:
        data = json.loads(path.read_text())
        created = float(data.get("created_at", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ""
    age = time.time() - created
    if data.get("session") != event.session_id or not math.isfinite(created) or not 0 <= age <= RECEIPT_MAX_AGE:
        return ""
    capsule = _clean(data.get("capsule"), CAPSULE_LIMIT)
    return capsule if capsule else ""


def _read_marker(context_root: Path, session_id: str, page: Path) -> Path:
    session = hashlib.sha256((session_id or "anonymous").encode()).hexdigest()[:16]
    name = hashlib.sha256(page.as_posix().encode()).hexdigest()[:16]
    return context_root / ".hook-reads" / session / name


def _mark_context_reads(event: Event, context_root: Path) -> None:
    for path in event.paths:
        if len(path.parts) < 2 or path.parts[0] != "context":
            continue
        page = Path(*path.parts[1:])
        marker = _read_marker(context_root, event.session_id, page)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()


def _tracking_pages(path: Path, context_root: Path) -> tuple[Path, ...]:
    rel = path.as_posix()
    pages = []
    for page in sorted(context_root.rglob("*.html")):
        relative = page.relative_to(context_root)
        if "docs" in relative.parts:
            continue
        tracking = tracks_status(page)
        if tracking["status"] != "tracked":
            continue
        if any(rel == pattern or fnmatch.fnmatch(rel, pattern) for pattern in tracking["tracks"]):
            pages.append(relative)
    return tuple(pages)


def _lock_gate(path: Path, event: Event, context_root: Path) -> Result:
    if len(path.parts) < 2 or path.parts[0] != "context" or path.suffix != ".html" or path.name == "index.html":
        return Result()
    page = context_root / Path(*path.parts[1:])
    if not page.exists():
        return Result()
    locked, owner = read_meta(page, "locked"), read_meta(page, "locked-by")
    agent = event.agent_id or f"hook-{event.session_id or 'session'}"
    if locked == "true" and owner in {agent, "orchestrator", ""}:
        return Result()
    if read_config(context_root).get("autoAcquireOnEdit") is False:
        if locked == "true":
            return block(f"{path.as_posix()} is locked by {owner or 'another agent'}; run start-task.py first")
        return block(f"{path.as_posix()} is not locked; run start-task.py first")
    script = context_root / "scripts" / "start-task.py"
    if not script.exists():
        return block(f"{path.as_posix()} is not locked; run start-task.py first")
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--page", page.relative_to(context_root).as_posix(),
             "--agent-id", agent, "--intent", "auto-acquire on edit", "--lines", "5", "--files", "1"],
            cwd=context_root.parent, text=True, capture_output=True, timeout=12,
        )
        status = json.loads(completed.stdout).get("status")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        status = ""
    if status in {"acquired", "broke_stale_lock"}:
        return Result()
    return block(f"cannot acquire lock on {path.as_posix()}; run start-task.py first")


def _edit_gate(event: Event, context_root: Path) -> Result:
    if event.unsafe_paths:
        return block("edit paths must stay inside the project")
    missing = []
    relevant = []
    project_root = context_root.parent.resolve()
    for path in event.paths:
        target = (project_root / path).resolve()
        try:
            target.relative_to(project_root)
        except ValueError:
            return block("edit paths must stay inside the project")
        if READ_ONLY_PARTS.intersection(path.parts):
            return block(f"{path.as_posix()} is in a read-only source directory")
        locked = _lock_gate(path, event, context_root)
        if not locked.allow:
            return locked
        if not path.parts or path.parts[0] in {"context", ".claude", ".codex"} or path.name in {"AGENTS.md", "CLAUDE.md", "MEMORY.md"}:
            continue
        for page in _tracking_pages(path, context_root):
            relevant.append(page)
            if not _read_marker(context_root, event.session_id, page).exists():
                missing.append(page)
    if missing:
        pages = ", ".join(f"context/{page.as_posix()}" for page in dict.fromkeys(missing))
        edited = ", ".join(path.as_posix() for path in event.paths)
        return block(f"read {pages} before editing {edited}")
    context = "Relevant context: " + ", ".join(f"context/{page.as_posix()}" for page in dict.fromkeys(relevant)) if relevant else ""
    return Result(context=_bounded(context, context_root, event.name) if context else "")


def dispatch(event: Event, context_root) -> Result:
    """Run the small shared lifecycle policy; matching hooks need no ordering."""
    root = Path(context_root)
    if event.name == "PreToolUse":
        return _edit_gate(event, root)
    if event.name == "SessionStart":
        firstmate = _firstmate_state(root)
        if firstmate:
            projects, status = firstmate
            summary = f"Firstmate root={_clean(str(root.parent), 500)}; registered={len(projects)}; validation={status}."
            return Result(context=_bounded(summary, root, event.name))
        return Result(context=_bounded("Read context/index.html before changing tracked work.", root, event.name))
    if event.name == "UserPromptSubmit":
        route = _firstmate_route(root, event.prompt)
        if re.search(r"\b(decision|failure|open question)\b", event.prompt, re.I):
            capture = "Capture durable decisions, failures, or open questions in context/capture-inbox.html."
            return Result(context=_bounded("; ".join(part for part in (route, capture) if part), root, event.name))
        return Result(context=_bounded(route, root, event.name) if route else "")
    if event.name == "PreCompact":
        _record_receipt(event, root)
        return Result(context="Context receipt recorded; restore only the current task capsule.")
    if event.name == "PostCompact":
        return Result(context=_restore_receipt(event, root))
    if event.name == "PostToolUse":
        if event.tool == "Read":
            _mark_context_reads(event, root)
            return Result()
        if event.paths and any(p.parts and p.parts[0] == "context" for p in event.paths):
            return Result(context=_validation_failure(root))
        return Result(context=_freshness_update(root) if event.paths else "")
    if event.name == "SubagentStart":
        route = _firstmate_route(root, " ".join((event.task, *event.scope)))
        context = "; ".join(part for part in (_capsule(event), route) if part)
        return Result(context=_bounded(context, root, event.name))
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
    if result.continue_ and event_name == "SubagentStop":
        return {"decision": "block", "reason": result.context or result.reason}
    if not result.allow:
        return {"decision": "block", "reason": result.reason}
    output = {"hookEventName": event_name}
    if result.context:
        output["additionalContext"] = result.context
    return {"hookSpecificOutput": output}


def _command_tokens(hook: object) -> list[str]:
    command = hook.get("command") if isinstance(hook, dict) else None
    if not isinstance(command, str):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _managed_hook(hook: object) -> bool:
    tokens = _command_tokens(hook)
    return any(
        token == f"--managed-group={MANAGED_GROUP}"
        or token == "--managed-group" and index + 1 < len(tokens) and tokens[index + 1] == MANAGED_GROUP
        for index, token in enumerate(tokens)
    )


def _legacy_hook(hook: object) -> bool:
    for token in _command_tokens(hook):
        path = Path(token)
        if path.name not in LEGACY_HOOK_NAMES or len(path.parts) < 3 or path.parts[-2] != "hooks":
            continue
        if path.parts[-3] in {"context", "context-architecture"}:
            return True
    return False


def _reconcile_group(group: object):
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        return group
    kept = [hook for hook in group["hooks"] if not (_managed_hook(hook) or _legacy_hook(hook))]
    if not kept:
        return None
    cleaned = json.loads(json.dumps(group))
    cleaned["hooks"] = kept
    return cleaned


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
            kept = [cleaned for group in groups if (cleaned := _reconcile_group(group)) is not None]
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
