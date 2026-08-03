"""Parse and validate typed context knowledge-graph nodes."""

from dataclasses import dataclass
from collections import deque
from datetime import datetime, timezone
import html
from pathlib import Path
import posixpath
import re


STATUSES = {
    "wiki": {"active", "superseded", "deprecated"},
    "decision": {"proposed", "accepted", "implemented", "superseded", "deprecated", "rejected"},
    "failure": {"open", "authorized", "blocked", "resolved", "deprecated"},
    "work": {"backlog", "active", "blocked", "done", "cancelled"},
}

TERMINAL_STATUSES = {
    "wiki": {"superseded", "deprecated"},
    "decision": {"superseded", "deprecated", "rejected"},
    "failure": {"resolved", "deprecated"},
    "work": {"done", "cancelled"},
}

PATH_KINDS = {
    "wiki": "wiki",
    "decisions": "decision",
    "failure-todos": "failure",
    "open-questions": "work",
    "workstreams": "work",
}

ROUTERS = {
    "wiki": "wiki.html",
    "decision": "decisions.html",
    "failure": "failure-todos.html",
    "work": "workstreams.html",
}

ROOT_NON_NODE_PAGES = {
    "index.html", "control-plane.html", "ledger.html", "agent-tree.html",
    "wiki.html", "decisions.html", "failure-todos.html", "workstreams.html",
    "history.html", "open-questions.html", "reproducibility.html",
    "run-intent.html", "recognized-commits.html",
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
    archived_at: str = ""
    topic: str = ""
    source_owner: str = ""


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


def _reference_id(reference: str) -> str:
    return reference.rsplit("#", 1)[-1] if "#" in reference else reference


def _link_errors(context_root: Path, node: Node, reference: str) -> list[str]:
    if "#" not in reference or "://" in reference:
        return []
    file_name, fragment = reference.rsplit("#", 1)
    target = node.path if not file_name else (node.path.parent / file_name).resolve()
    try:
        target.relative_to(context_root.resolve())
    except ValueError:
        return [f"missing link file {file_name}"]
    if not target.is_file():
        return [f"missing link file {file_name}"]
    content = target.read_text(errors="replace")
    if not re.search(rf'\bid\s*=\s*(["\']){re.escape(fragment)}\1', content) and _meta(content).get("node-id") != fragment:
        return [f"missing link fragment {fragment}"]
    return []


def load_nodes(context_root: Path) -> list[Node]:
    nodes = []
    for path in sorted(context_root.rglob("*.html")):
        if path.name == "archive.html" or ".locks" in path.parts or "docs" in path.parts:
            continue
        content = path.read_text(errors="replace")
        meta = _meta(content)
        path_kind = _path_kind(path.relative_to(context_root))
        is_v2 = meta.get("contract-version") == "2"
        relative = path.relative_to(context_root)
        root_wiki = len(relative.parts) == 1 and path.name not in ROOT_NON_NODE_PAGES
        articles = list(re.finditer(r"<article\b([^>]*)>(.*?)</article>", content, flags=re.I | re.S))
        decision_cards = [article for article in articles if "decision" in _attrs(article.group(1)).get("class", "").split()]
        candidates = articles[:1] if is_v2 else decision_cards or articles[:1]
        if not candidates:
            candidates = [None]
        for article in candidates:
            attrs = _attrs(article.group(1)) if article else {}
            body = article.group(2) if article else content
            legacy_kind = "decision" if "decision" in attrs.get("class", "").split() else "wiki" if root_wiki else ""
            if not path_kind and not is_v2 and not legacy_kind:
                continue
            node_id = _field(attrs, meta, body, "node-id") or _field(attrs, meta, body, "id")
            if not node_id and (path_kind or legacy_kind):
                node_id = path.stem
            if not node_id:
                continue
            kind = _field(attrs, meta, body, "kind") or path_kind or legacy_kind or ("wiki" if is_v2 else "")
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
                archived_at=_field(attrs, meta, body, "archived-at"),
                topic=_field(attrs, meta, body, "topic"),
                source_owner=_field(attrs, meta, body, "source-owner"),
            ))
    return nodes


def heads(nodes: list[Node], kind: str) -> list[Node]:
    return [node for node in nodes if node.kind == kind and node.parent is None]


def _parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except ValueError:
        return None


def _relative_node_path(path: Path) -> str:
    for index in range(len(path.parts) - 2, -1, -1):
        if path.parts[index] in PATH_KINDS:
            return Path(*path.parts[index:]).as_posix()
    return path.name


def render_history(nodes: list[Node]) -> str:
    """Render a concise chronological link index for archived terminal nodes."""
    historical = [
        node for node in nodes
        if node.archived
        and node.status in TERMINAL_STATUSES.get(node.kind, set())
        and _parse_timestamp(node.archived_at) is not None
    ]
    historical.sort(key=lambda node: (_parse_timestamp(node.archived_at), node.node_id))
    return "".join(
        f'<li data-node-id="{html.escape(node.node_id, quote=True)}">'
        f'<time datetime="{html.escape(node.archived_at, quote=True)}">{html.escape(node.archived_at)}</time> '
        f'<a href="{html.escape(_relative_node_path(node.path), quote=True)}#{html.escape(node.node_id, quote=True)}">'
        f'{html.escape(node.node_id)}</a> {html.escape(node.kind)} {html.escape(node.status)}</li>\n'
        for node in historical
    )


def _normalized_basis(prefix: str, value: str) -> str:
    value = " ".join(value.split())
    if prefix in {"affects", "source-owner"}:
        slash_terminated = prefix == "source-owner" and value.replace("\\", "/").endswith("/")
        value = posixpath.normpath(value.replace("\\", "/"))
        if slash_terminated and value != ".":
            value += "/"
    return f"{prefix}:{value}" if value and value != "." else ""


def consolidation_candidates(nodes: list[Node]) -> tuple[dict, ...]:
    """Suggest exact shared bases for three or more live heads; never mutate nodes."""
    groups: dict[tuple[str, str], set[str]] = {}
    for node in nodes:
        if node.archived or node.parent or node.status in TERMINAL_STATUSES.get(node.kind, set()):
            continue
        bases = {_normalized_basis("affects", value) for value in node.affects}
        bases.add(_normalized_basis("topic", node.topic))
        bases.add(_normalized_basis("source-owner", node.source_owner))
        for basis in bases - {""}:
            groups.setdefault((node.kind, basis), set()).add(node.node_id)
    return tuple(
        {"basis": basis, "node_ids": tuple(sorted(node_ids))}
        for (_kind, basis), node_ids in sorted(groups.items())
        if len(node_ids) >= 3
    )


def _href_paths(context_root: Path, page: Path) -> list[Path]:
    paths = []
    for href in re.findall(r'href\s*=\s*(["\'])(.*?)\1', page.read_text(errors="replace"), flags=re.I | re.S):
        raw = html.unescape(href[1]).split("#", 1)[0].split("?", 1)[0].strip()
        if not raw or raw.startswith(("/", "mailto:", "http:", "https:")):
            continue
        path = (page.parent / raw).resolve()
        try:
            path.relative_to(context_root.resolve())
        except ValueError:
            continue
        if path.suffix == ".html" and path.is_file():
            paths.append(path)
    return paths


def _router_nodes(context_root: Path, kind: str, nodes: list[Node]) -> list[Node]:
    router = context_root / ROUTERS[kind]
    if not router.exists():
        return []
    graph = re.search(r'<section\b[^>]*(?:id|class)=["\'][^"\']*\bgraph\b[^"\']*["\'][^>]*>(.*?)</section>', router.read_text(errors="replace"), flags=re.I | re.S)
    if not graph:
        return []
    by_path: dict[Path, list[Node]] = {}
    for node in nodes:
        by_path.setdefault(node.path.resolve(), []).append(node)
    listed = []
    for href in re.findall(r'href\s*=\s*(["\'])(.*?)\1', graph.group(1), flags=re.I | re.S):
        raw, _, fragment = html.unescape(href[1]).partition("#")
        raw = raw.split("?", 1)[0].strip()
        if not raw:
            continue
        path = (router.parent / raw).resolve()
        candidates = by_path.get(path, [])
        node = next((candidate for candidate in candidates if candidate.node_id == fragment), None) if fragment else candidates[0] if len(candidates) == 1 else None
        if node and node not in listed:
            listed.append(node)
    return listed


def router_heads(context_root: Path, kind: str) -> list[Node]:
    """Return live HEAD entries linked in a typed family router."""
    return [node for node in _router_nodes(context_root, kind, load_nodes(context_root))
            if node.kind == kind and not node.archived and node.parent is None]


def reachable_nodes(context_root: Path, nodes: list[Node] | None = None) -> list[Node]:
    """Return nodes reached by explicit href BFS from index.html."""
    index = context_root / "index.html"
    if not index.exists():
        return []
    seen = {index.resolve()}
    queue = deque([index])
    while queue:
        for target in _href_paths(context_root, queue.popleft()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return [node for node in (nodes if nodes is not None else load_nodes(context_root))
            if node.path.resolve() in seen]


def validate_graphs(context_root: Path, nodes: list[Node]) -> list[str]:
    """Return deterministic diagnostics; never modify context files."""
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
        relative = node.path.relative_to(context_root)
        if expected_dir and relative.parts and relative.parts[0] != expected_dir and not (node.kind == "wiki" and len(relative.parts) == 1):
            errors.append((node.path, f"{node.kind} node stored outside {expected_dir}"))
        if node.status not in STATUSES.get(node.kind, set()):
            errors.append((node.path, f"invalid {node.kind} status {node.status}"))
        if not node.statement:
            errors.append((node.path, "missing durable statement"))
        if node.archived_at and _parse_timestamp(node.archived_at) is None:
            relative_path = node.path.relative_to(context_root).as_posix()
            errors.append((node.path, f"{relative_path}: invalid archived-at timestamp {node.archived_at}"))
        references = ((node.parent,) if node.parent else ()) + node.children + node.related + node.tracks + node.affects
        for reference in references:
            for message in _link_errors(context_root, node, reference):
                errors.append((node.path, message))
        if node.parent:
            parent_id = _reference_id(node.parent)
            parent = one.get(parent_id)
            if not parent:
                errors.append((node.path, f"unknown parent {parent_id}"))
            else:
                if parent.kind != node.kind:
                    errors.append((node.path, f"{node.kind} node parent must be {node.kind}"))
                if not node.archived and parent.archived:
                    errors.append((node.path, "live node cannot use archived parent"))
                if node.node_id not in {_reference_id(child) for child in parent.children}:
                    errors.append((node.path, "parent/child link is not reciprocal"))
        for child_ref in node.children:
            child_id = _reference_id(child_ref)
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
        while current.parent and _reference_id(current.parent) in one:
            current = one[_reference_id(current.parent)]
            if current.node_id in chain or current.node_id == node.node_id:
                cycle_members.update(item.node_id for item in chain)
                cycle_members.add(current.node_id)
                errors.append((node.path, "parent cycle"))
                break
            chain.append(current)

    for kind, router_name in ROUTERS.items():
        router = context_root / router_name
        if not router.exists():
            continue  # Preserve pre-router contexts.
        listed = _router_nodes(context_root, kind, nodes)
        listed_ids = {node.node_id for node in listed}
        for node in listed:
            if node.kind != kind:
                errors.append((router, f"{kind} router links {node.kind} node {node.node_id}"))
            elif node.archived:
                errors.append((router, "router contains archived node"))
            elif node.parent:
                errors.append((router, f"router contains non-head {node.node_id}"))
        for node in heads(nodes, kind):
            if not node.archived and node.node_id not in listed_ids:
                errors.append((router, f"router omits live head {node.node_id}"))

    if (context_root / "index.html").exists():
        reachable = {node.node_id for node in reachable_nodes(context_root, nodes)}
        for node in nodes:
            if not node.archived and node.node_id not in reachable:
                errors.append((node.path, f"unreachable live node {node.node_id}"))
    return [message for _, message in sorted(errors, key=lambda item: (item[0].as_posix(), item[1]))]
