"""Parse and validate typed context knowledge-graph nodes."""

from dataclasses import dataclass
import html
from pathlib import Path
import re


STATUSES = {
    "wiki": {"active", "superseded", "deprecated"},
    "decision": {"proposed", "accepted", "implemented", "superseded", "deprecated", "rejected"},
    "failure": {"open", "authorized", "blocked", "resolved", "deprecated"},
    "work": {"backlog", "active", "blocked", "done", "cancelled"},
}

PATH_KINDS = {
    "wiki": "wiki",
    "decisions": "decision",
    "failure-todos": "failure",
    "open-questions": "work",
    "workstreams": "work",
}


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    status: str
    path: Path
    archived: bool
    parent: str | None
    children: tuple[str, ...]
    related: tuple[str, ...]
    tracks: tuple[str, ...]
    affects: tuple[str, ...]
    statement: str


def _attrs(raw: str) -> dict[str, str]:
    values = {}
    for match in re.finditer(r'''([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^>\s]+))''', raw):
        values[match.group(1).lower()] = html.unescape(next(value for value in match.groups()[1:] if value is not None))
    return values


def _strip(raw: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def _meta(content: str) -> dict[str, str]:
    values = {}
    for match in re.finditer(r"<meta\b([^>]*)>", content, flags=re.I):
        attrs = _attrs(match.group(1))
        if attrs.get("name"):
            values[attrs["name"].lower()] = attrs.get("content", "")
    return values


def _field(attrs: dict[str, str], meta: dict[str, str], body: str, name: str) -> str:
    value = attrs.get(f"data-{name}") or attrs.get(name) or meta.get(name, "")
    if value:
        return value.strip()
    match = re.search(rf"<dt[^>]*>\s*{re.escape(name)}\s*</dt>\s*<dd[^>]*>(.*?)</dd>", body, flags=re.I | re.S)
    return _strip(match.group(1)) if match else ""


def _values(raw: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in raw.split(",") if value.strip())


def _path_kind(path: Path) -> str | None:
    for part in reversed(path.parts[:-1]):
        if part in PATH_KINDS:
            return PATH_KINDS[part]
    return None


def _default_status(kind: str) -> str:
    return {"wiki": "active", "decision": "proposed", "failure": "open", "work": "backlog"}.get(kind, "")


def _is_v2(path: Path) -> bool:
    return _meta(path.read_text(errors="replace")).get("contract-version") == "2"


def load_nodes(context_root: Path) -> list[Node]:
    nodes = []
    for path in sorted(context_root.rglob("*.html")):
        if path.name == "archive.html" or ".locks" in path.parts or "docs" in path.parts:
            continue
        content = path.read_text(errors="replace")
        meta = _meta(content)
        path_kind = _path_kind(path.relative_to(context_root))
        is_v2 = meta.get("contract-version") == "2"
        if not path_kind and not is_v2:
            continue
        article = re.search(r"<article\b([^>]*)>(.*?)</article>", content, flags=re.I | re.S)
        attrs = _attrs(article.group(1)) if article else {}
        body = article.group(2) if article else content
        node_id = _field(attrs, meta, body, "node-id") or _field(attrs, meta, body, "id")
        if not node_id and path_kind:
            node_id = path.stem
        if not node_id:
            continue
        kind = _field(attrs, meta, body, "kind") or path_kind
        if not kind:
            continue
        status = _field(attrs, meta, body, "status").lower() or _default_status(kind)
        parent = _field(attrs, meta, body, "parent") or None
        statement = _field(attrs, meta, body, "statement")
        if not statement:
            match = re.search(r'<(?:section|p)\b[^>]*(?:id|class)=["\'][^"\']*statement[^"\']*["\'][^>]*>(.*?)</(?:section|p)>', body, flags=re.I | re.S)
            statement = _strip(match.group(1)) if match else ""
        nodes.append(Node(
            node_id=node_id,
            kind=kind,
            status=status,
            path=path,
            archived="archive" in path.parts or "archived" in path.parts,
            parent=parent,
            children=_values(_field(attrs, meta, body, "children")),
            related=_values(_field(attrs, meta, body, "related")),
            tracks=_values(_field(attrs, meta, body, "tracks")),
            affects=_values(_field(attrs, meta, body, "affects")),
            statement=statement,
        ))
    return nodes


def heads(nodes: list[Node], kind: str) -> list[Node]:
    return [node for node in nodes if node.kind == kind and node.parent is None]


def validate_graphs(context_root: Path, nodes: list[Node]) -> list[str]:
    """Return deterministic diagnostics; never modify context files."""
    del context_root
    errors: list[tuple[Path, str]] = []
    by_id: dict[str, list[Node]] = {}
    for node in nodes:
        by_id.setdefault(node.node_id, []).append(node)
    for same_id in by_id.values():
        if len(same_id) > 1:
            for node in same_id:
                if _is_v2(node.path):
                    errors.append((node.path, f"duplicate node id {node.node_id}"))

    one = {node_id: group[0] for node_id, group in by_id.items()}
    for node in nodes:
        if not _is_v2(node.path):
            continue
        expected_dir = {"wiki": "wiki", "decision": "decisions", "failure": "failure-todos", "work": "workstreams"}.get(node.kind)
        if expected_dir and expected_dir not in node.path.parts:
            errors.append((node.path, f"{node.kind} node stored outside {expected_dir}"))
        if node.status not in STATUSES.get(node.kind, set()):
            errors.append((node.path, f"invalid {node.kind} status {node.status}"))
        if not node.statement:
            errors.append((node.path, "missing durable statement"))
        if node.parent:
            parent = one.get(node.parent)
            if not parent:
                errors.append((node.path, f"unknown parent {node.parent}"))
            else:
                if parent.kind != node.kind:
                    errors.append((node.path, f"{node.kind} node parent must be {node.kind}"))
                if not node.archived and parent.archived:
                    errors.append((node.path, "live node cannot use archived parent"))
                if node.node_id not in parent.children:
                    errors.append((node.path, "parent/child link is not reciprocal"))
        for child_id in node.children:
            child = one.get(child_id)
            if not child:
                errors.append((node.path, f"unknown child {child_id}"))
            elif child.parent != node.node_id:
                errors.append((node.path, "parent/child link is not reciprocal"))

    cycle_members = set()
    for node in nodes:
        if not _is_v2(node.path) or node.node_id in cycle_members:
            continue
        chain = []
        current = node
        while current.parent and current.parent in one:
            current = one[current.parent]
            if current.node_id in chain or current.node_id == node.node_id:
                cycle_members.update(item.node_id for item in chain)
                cycle_members.add(current.node_id)
                errors.append((node.path, "parent cycle"))
                break
            chain.append(current)
    return [message for _, message in sorted(errors, key=lambda item: (item[0].as_posix(), item[1]))]
