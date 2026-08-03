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
    context_mutex,
    read_config,
    read_ledger_events,
    read_meta,
    repo_root,
)
from knowledge_graph import Node, load_nodes


HARD_MAX_CHARS = 4000
HARD_MAX_NODES = 8
MODEL_GRAPH_DIRS = {"wiki", "decisions", "failure-todos", "open-questions", "workstreams"}
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
    links: tuple[str, ...]
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


def _task_fields(task: object) -> tuple[str, str, tuple[str, ...]]:
    if isinstance(task, Mapping):
        description = _one_line(task.get("task") or task.get("description"))
        result = _one_line(task.get("result") or task.get("expected_result"))
        raw_links = task.get("links", ())
        if isinstance(raw_links, str):
            raw_links = (raw_links,)
        if not isinstance(raw_links, (list, tuple)):
            raise CapsuleError("task links must be a list")
        links = tuple(sorted(set(_one_line(link) for link in raw_links if _one_line(link))))
    else:
        description = _one_line(task)
        result = "Complete the scoped task."
        links = ()
    if not description:
        raise CapsuleError("task is required")
    return description, result or "Complete the scoped task.", links


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


def _is_agent_visible(context_root: Path, node: Node) -> bool:
    relative = node.path.relative_to(context_root)
    return (
        bool(relative.parts)
        and relative.parts[0] in MODEL_GRAPH_DIRS
        and read_meta(node.path, "visibility").strip().lower() in {"agent", "model", "public"}
    )


def _linked_ids(context_root: Path, nodes: list[Node], links: tuple[str, ...]) -> set[str]:
    by_id = {node.node_id: node for node in nodes}
    linked = set()
    for reference in links:
        if "://" in reference or reference.startswith("/") or ".." in Path(reference.split("#", 1)[0]).parts:
            raise CapsuleError(f"task link escapes canonical context: {reference}")
        file_name, separator, node_id = reference.rpartition("#")
        if not separator:
            node_id, file_name = reference, ""
        node = by_id.get(node_id)
        if node is None:
            raise CapsuleError(f"missing linked node {node_id}")
        if file_name and Path(file_name).as_posix() != node.path.relative_to(context_root).as_posix():
            raise CapsuleError(f"task link does not resolve to node {node_id}")
        linked.add(node_id)
    return linked


def _is_relevant(node: Node, paths: tuple[str, ...], linked_ids: set[str]) -> bool:
    if node.node_id in linked_ids:
        return True
    targets = tuple(node.affects) + tuple(node.tracks)
    if not paths or not targets:
        return False
    return any(
        target != "context-only" and (path == target or fnmatch.fnmatch(path, target))
        for path in paths
        for target in targets
    )


def _nodes(context_root: Path, paths: tuple[str, ...], links: tuple[str, ...]) -> list[Node]:
    root = context_root.resolve()
    for path in context_root.rglob("*.html"):
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise CapsuleError(f"node path escapes canonical context: {path.relative_to(context_root)}") from exc
    loaded = load_nodes(context_root)
    linked_ids = _linked_ids(context_root, loaded, links)
    selected = [
        node for node in loaded
        if not node.archived
        and node.status in VISIBLE.get(node.kind, set())
        and _is_agent_visible(context_root, node)
        and _is_relevant(node, paths, linked_ids)
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
    result = sorted(
        (node for node in selected if _one_line(node.statement)),
        key=lambda node: (node.kind, node.node_id, node.path.as_posix()),
    )
    missing = linked_ids - {node.node_id for node in result}
    if missing:
        raise CapsuleError(f"linked node is not agent-visible: {sorted(missing)[0]}")
    return result


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
        limit = int(max_chars)
        configured_nodes = int(read_config(context_root).get("taskCapsuleMaxNodes", HARD_MAX_NODES))
    except (TypeError, ValueError) as exc:
        raise CapsuleError("invalid task capsule budget") from exc
    if limit <= 0:
        raise CapsuleError("task capsule budget must be positive")
    limit = min(HARD_MAX_CHARS, limit)
    max_nodes = max(0, min(HARD_MAX_NODES, configured_nodes))
    description, expected, links = _task_fields(task)
    scope = _scope_paths(context_root, paths)
    text = _header(description, expected, scope, role, limit)
    included = []
    hashes = {}
    for node in _nodes(context_root, scope, links):
        if len(included) >= max_nodes:
            break
        link = f"{node.path.relative_to(context_root).as_posix()}#{node.node_id}"
        statement = _one_line(node.statement)
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
        links=links,
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
        "budget": capsule.max_chars,
        "chars": len(capsule.text),
        "task": capsule.task,
        "result": capsule.result,
        "paths": list(capsule.paths),
        "links": list(capsule.links),
        "role": capsule.role,
        "max_chars": capsule.max_chars,
    }
    if restoration_of:
        record["restoration_of"] = restoration_of
    record["receipt_id"] = _receipt_digest(record)
    append_ledger_record(context_root, record)
    return record


def _receipt_digest(record: Mapping) -> str:
    body = {key: value for key, value in record.items() if key != "receipt_id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_receipt(record: Mapping) -> None:
    node_ids = record.get("node_ids")
    hashes = record.get("source_hashes")
    paths = record.get("paths")
    links = record.get("links")
    if record.get("event") != "task_capsule" or not isinstance(node_ids, list) or not all(isinstance(v, str) for v in node_ids):
        raise CapsuleError("receipt schema is malformed")
    if len(node_ids) != len(set(node_ids)) or len(node_ids) > HARD_MAX_NODES:
        raise CapsuleError("receipt node list is malformed")
    if not isinstance(hashes, Mapping):
        raise CapsuleError("receipt source hashes are malformed")
    for node_id in node_ids:
        if not re.fullmatch(r"[0-9a-f]{64}", str(hashes.get(node_id, ""))):
            raise CapsuleError(f"missing source hash for {node_id}")
    if set(hashes) != set(node_ids):
        raise CapsuleError("receipt source hashes are malformed")
    if not isinstance(paths, list) or not all(isinstance(v, str) for v in paths):
        raise CapsuleError("receipt scope is malformed")
    if not isinstance(links, list) or not all(isinstance(v, str) for v in links):
        raise CapsuleError("receipt links are malformed")
    if not isinstance(record.get("budget"), int) or not 0 < record["budget"] <= HARD_MAX_CHARS:
        raise CapsuleError("receipt budget is malformed")
    if not isinstance(record.get("chars"), int) or not 0 <= record["chars"] <= record["budget"]:
        raise CapsuleError("receipt character count is malformed")
    for field in ("time", "project_id", "session", "turn", "task", "result", "role", "receipt_id"):
        if not isinstance(record.get(field), str):
            raise CapsuleError(f"receipt {field} is malformed")
    if not re.fullmatch(r"[0-9a-f]{64}", record["project_id"]):
        raise CapsuleError("receipt project identity is malformed")
    if record.get("max_chars") != record["budget"]:
        raise CapsuleError("receipt max_chars is malformed")
    try:
        datetime.fromisoformat(record["time"])
    except ValueError as exc:
        raise CapsuleError("receipt time is malformed") from exc
    lineage = record.get("restoration_of")
    if lineage is not None and not re.fullmatch(r"[0-9a-f]{64}", str(lineage)):
        raise CapsuleError("receipt restoration lineage is malformed")
    if record["receipt_id"] != _receipt_digest(record):
        raise CapsuleError("receipt digest does not match content")


def _receipt(context_root: Path, receipt: object) -> dict:
    external = dict(receipt) if isinstance(receipt, Mapping) else None
    if external is not None:
        _validate_receipt(external)
        if external.get("project_id") != _project_id(context_root):
            raise CapsuleError("receipt belongs to a different project")
        receipt_id = external.get("receipt_id")
    else:
        receipt_id = receipt
    with context_mutex(context_root, "ledger"):
        matches = [record for record in read_ledger_events(context_root) if record.get("receipt_id") == receipt_id]
    if len(matches) != 1:
        raise CapsuleError(f"receipt is not uniquely present in ledger: {receipt_id}")
    canonical = matches[0]
    _validate_receipt(canonical)
    if external is not None and external != canonical:
        raise CapsuleError("receipt does not match ledger evidence")
    return canonical


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
    scope = _scope_paths(context_root, previous["paths"])
    if list(scope) != previous["paths"]:
        raise CapsuleError("receipt scope is not canonical")
    relevant = {node.node_id: node for node in _nodes(context_root, scope, tuple(previous["links"]))}
    for node_id in previous.get("node_ids", []):
        if node_id not in relevant or not relevant[node_id].path.is_file():
            if not any(node.node_id == node_id for node in load_nodes(context_root)):
                raise CapsuleError(f"missing node {node_id}")
            raise CapsuleError(f"node {node_id} is no longer relevant")
        if not relevant[node_id].path.is_file():
            raise CapsuleError(f"missing node {node_id}")
    capsule = build_capsule(
        context_root,
        {"task": previous.get("task"), "result": previous.get("result"), "links": previous["links"]},
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
