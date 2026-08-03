"""Build bounded model context while keeping control-plane evidence private."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from context_utils import (
    ContextRootError,
    append_ledger_record,
    canonical_context_root,
    read_config,
    read_ledger_events,
    repo_root,
)
from knowledge_graph import Node, load_nodes


HARD_MAX_CHARS = 4000
HARD_MAX_NODES = 8
PRIVATE_TEXT = re.compile(
    r"ledger(?:-events\.ndjson)?|mutex|receipt(?:_id)?|daily[_ -]hygiene|"
    r"project[-_]registry|archived-at|hookspecificoutput|graph schema|"
    r"freshness algorithm|consolidation heuristic|hook wiring|migration rules?",
    re.I,
)
VISIBLE = {
    "wiki": {"active"},
    "decision": {"accepted", "implemented"},
    "failure": {"open", "authorized", "blocked"},
    "work": {"blocked"},
}
LABEL = {"wiki": "Fact", "decision": "Decision", "failure": "Blocker", "work": "Blocker"}


class CapsuleError(ValueError):
    pass


@dataclass(frozen=True)
class Capsule:
    text: str
    node_ids: tuple[str, ...]
    source_hashes: dict[str, str]
    task: str
    result: str
    paths: tuple[str, ...]
    role: str
    max_chars: int


def _one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def _ellipsize(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1].rstrip() + "…"


def _task_fields(task: object) -> tuple[str, str]:
    if isinstance(task, Mapping):
        description = _one_line(task.get("task") or task.get("description"))
        result = _one_line(task.get("result") or task.get("expected_result"))
    else:
        description = _one_line(task)
        result = "Complete the scoped task."
    if not description:
        raise CapsuleError("task is required")
    return description, result or "Complete the scoped task."


def _scope_paths(context_root: Path, paths: object) -> tuple[str, ...]:
    project = repo_root(context_root).resolve()
    normalized = []
    for value in paths or ():
        raw = _one_line(value).replace("\\", "/")
        candidate = Path(raw)
        if not raw or candidate.is_absolute() or ".." in candidate.parts:
            raise CapsuleError(f"scope path escapes project: {value}")
        resolved = (project / candidate).resolve()
        try:
            resolved.relative_to(project)
        except ValueError as exc:
            raise CapsuleError(f"scope path escapes project: {value}") from exc
        normalized.append(candidate.as_posix())
    return tuple(sorted(set(normalized)))


def _is_relevant(node: Node, paths: tuple[str, ...]) -> bool:
    targets = tuple(node.affects) + tuple(node.tracks)
    if "context-only" in targets:
        return True
    if not paths or not targets:
        return False
    return any(path == target or fnmatch.fnmatch(path, target) for path in paths for target in targets)


def _nodes(context_root: Path, paths: tuple[str, ...]) -> list[Node]:
    root = context_root.resolve()
    for path in context_root.rglob("*.html"):
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise CapsuleError(f"node path escapes canonical context: {path.relative_to(context_root)}") from exc
    selected = [
        node for node in load_nodes(context_root)
        if not node.archived
        and node.status in VISIBLE.get(node.kind, set())
        and _is_relevant(node, paths)
    ]
    seen = set()
    for node in selected:
        if node.node_id in seen:
            raise CapsuleError(f"duplicate node {node.node_id}")
        seen.add(node.node_id)
        if not _one_line(node.statement):
            content = node.path.read_text(errors="replace")
            if re.search(r'<meta\s+name=["\']contract-version["\']\s+content=["\']2["\']', content, re.I):
                raise CapsuleError(f"{node.path.relative_to(context_root)}: missing statement")
    return sorted(
        (node for node in selected if _one_line(node.statement)),
        key=lambda node: (node.kind, node.node_id, node.path.as_posix()),
    )


def _header(task: str, result: str, paths: tuple[str, ...], role: str, limit: int) -> str:
    scope = ", ".join(paths) if paths else "task only"
    fixed = f"Task: \nResult: \nRole: {_one_line(role)}\nScope: {_one_line(scope)}"
    available = max(2, limit - len(fixed))
    task_limit = available // 2
    result_limit = available - task_limit
    return (
        f"Task: {_ellipsize(task, task_limit)}\n"
        f"Result: {_ellipsize(result, result_limit)}\n"
        f"Role: {_one_line(role)}\nScope: {_one_line(scope)}"
    )[:limit]


def build_capsule(
    context_root: Path,
    task: object,
    paths: object,
    role: str,
    max_chars: int = HARD_MAX_CHARS,
) -> Capsule:
    context_root = Path(context_root).resolve()
    if not (context_root / "index.html").is_file():
        raise CapsuleError(f"canonical context is missing index.html: {context_root}")
    try:
        canonical = canonical_context_root(repo_root(context_root))
    except ContextRootError as exc:
        raise CapsuleError(str(exc)) from exc
    if canonical.resolve() != context_root:
        raise CapsuleError(f"context root is not canonical: {context_root}")
    try:
        limit = min(HARD_MAX_CHARS, max(64, int(max_chars)))
        configured_nodes = int(read_config(context_root).get("taskCapsuleMaxNodes", HARD_MAX_NODES))
    except (TypeError, ValueError) as exc:
        raise CapsuleError("invalid task capsule budget") from exc
    max_nodes = max(0, min(HARD_MAX_NODES, configured_nodes))
    description, expected = _task_fields(task)
    scope = _scope_paths(context_root, paths)
    text = _header(description, expected, scope, role, limit)
    included = []
    hashes = {}
    for node in _nodes(context_root, scope):
        if len(included) >= max_nodes:
            break
        link = f"{node.path.relative_to(context_root).as_posix()}#{node.node_id}"
        statement = _one_line(node.statement)
        if PRIVATE_TEXT.search(statement) or PRIVATE_TEXT.search(link):
            continue
        prefix = f"\n- {LABEL[node.kind]}: "
        suffix = f" [{link}]"
        remaining = limit - len(text) - len(prefix) - len(suffix)
        if remaining <= 1:
            continue
        text += prefix + _ellipsize(statement, remaining) + suffix
        included.append(node)
        hashes[node.node_id] = hashlib.sha256(node.path.read_bytes()).hexdigest()
    return Capsule(
        text=text,
        node_ids=tuple(node.node_id for node in included),
        source_hashes=hashes,
        task=description,
        result=expected,
        paths=scope,
        role=_one_line(role),
        max_chars=limit,
    )


def _project_id(context_root: Path) -> str:
    return hashlib.sha256(str(context_root.resolve()).encode()).hexdigest()


def record_receipt(
    context_root: Path,
    capsule: Capsule,
    *,
    session: str = "",
    turn: str = "",
    restoration_of: str | None = None,
) -> dict:
    context_root = Path(context_root).resolve()
    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": "task_capsule",
        "page": "",
        "agent": capsule.role,
        "status": "restored" if restoration_of else "built",
        "details": "bounded task context",
        "project_id": _project_id(context_root),
        "node_ids": list(capsule.node_ids),
        "source_hashes": dict(capsule.source_hashes),
        "session": _one_line(session),
        "turn": _one_line(turn),
        "budget": len(capsule.text),
        "task": capsule.task,
        "result": capsule.result,
        "paths": list(capsule.paths),
        "role": capsule.role,
        "max_chars": capsule.max_chars,
    }
    if restoration_of:
        record["restoration_of"] = restoration_of
    identity = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    record["receipt_id"] = hashlib.sha256(identity).hexdigest()
    append_ledger_record(context_root, record)
    return record


def _receipt(context_root: Path, receipt: object) -> dict:
    if isinstance(receipt, Mapping):
        return dict(receipt)
    for record in reversed(read_ledger_events(context_root)):
        if record.get("receipt_id") == receipt:
            return record
    raise CapsuleError(f"missing receipt {receipt}")


def restore_capsule(
    context_root: Path,
    receipt: object,
    *,
    session: str = "",
    turn: str = "",
) -> tuple[Capsule, dict]:
    context_root = Path(context_root).resolve()
    previous = _receipt(context_root, receipt)
    if previous.get("project_id") != _project_id(context_root):
        raise CapsuleError("receipt belongs to a different project")
    current = {node.node_id: node for node in load_nodes(context_root)}
    hashes = previous.get("source_hashes")
    if not isinstance(hashes, Mapping):
        raise CapsuleError("receipt source hashes are malformed")
    for node_id in previous.get("node_ids", []):
        if node_id not in current or not current[node_id].path.is_file():
            raise CapsuleError(f"missing node {node_id}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(hashes.get(node_id, ""))):
            raise CapsuleError(f"missing source hash for {node_id}")
    capsule = build_capsule(
        context_root,
        {"task": previous.get("task"), "result": previous.get("result")},
        previous.get("paths", []),
        str(previous.get("role", "worker")),
        int(previous.get("max_chars", HARD_MAX_CHARS)),
    )
    return capsule, record_receipt(
        context_root,
        capsule,
        session=session,
        turn=turn,
        restoration_of=str(previous.get("receipt_id", "")),
    )
