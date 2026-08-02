#!/usr/bin/env python3
"""Reverse-index: given a file path, find relevant context (tracking pages, decisions, failure-todos).

Used by the PreToolUse hook to inject context the agent needs before editing.
Output goes to stderr so the agent sees it without blocking.
"""

import fnmatch
import re
import sys
from pathlib import Path

from context_utils import find_context_root, read_meta, tracks_status, repo_root, read_config


def build_reverse_index(context_root: Path) -> dict:
    """Build file-pattern → [page_path] mapping from all context pages."""
    index = {}
    for html_file in sorted(context_root.rglob("*.html")):
        if "docs" in html_file.parts:
            continue
        tracking = tracks_status(html_file)
        if tracking["status"] != "tracked":
            continue
        for track in tracking["tracks"]:
            index.setdefault(track, []).append(html_file)
    return index


def find_tracking_pages(file_path: str, reverse_index: dict, root: Path) -> list[Path]:
    """Find context pages that track the given file."""
    matches = []
    try:
        rel = str(Path(file_path).resolve().relative_to(root.resolve()))
    except ValueError:
        return matches

    for pattern, pages in reverse_index.items():
        if rel == pattern or fnmatch.fnmatch(rel, pattern):
            matches.extend(pages)
    return list(set(matches))


def build_decision_graph(decisions_dir: Path) -> dict:
    """Build dec-id → {title, status, parents} mapping from all decision files."""
    graph = {}
    for dec_file in sorted(decisions_dir.glob("dec-*.html")):
        dec_id = dec_file.stem
        content = dec_file.read_text(errors="replace")
        title = read_meta(dec_file, "title") or dec_id
        status = read_meta(dec_file, "status")
        parents = []
        # Format 1: <meta name="builds-on" content="dec-xxx,...">
        meta_val = read_meta(dec_file, "builds-on")
        if meta_val:
            parents.extend([p.strip() for p in meta_val.split(",") if p.strip()])
        # Format 2: data-builds-on="dec-xxx" on article tags
        for m in re.finditer(r'data-builds-on="([^"]+)"', content):
            parents.extend([p.strip() for p in m.group(1).split(",") if p.strip()])
        # Format 3: <li><strong>builds-on</strong>: <a href="./dec-xxx.html">
        for m in re.finditer(r'<li><strong>builds-on</strong>.*?<a href="\./([^"]+)\.html"', content):
            parents.append(m.group(1))
        graph[dec_id] = {"title": title, "status": status, "parents": list(set(parents)), "file": dec_file}
    return graph


def walk_ancestors(dec_id: str, graph: dict, max_depth: int = 5) -> list[dict]:
    """Walk builds-on chain upward. Returns ancestors in order from immediate parent to root."""
    ancestors = []
    visited = {dec_id}
    queue = list(graph.get(dec_id, {}).get("parents", []))
    depth = 0
    while queue and depth < max_depth:
        next_queue = []
        for parent_id in queue:
            if parent_id in visited:
                continue
            visited.add(parent_id)
            node = graph.get(parent_id)
            if not node:
                continue
            if node["status"] in ("superseded", "deprecated", "rejected"):
                continue
            ancestors.append({"id": parent_id, "title": node["title"], "status": node["status"], "depth": depth + 1})
            next_queue.extend(node.get("parents", []))
        queue = next_queue
        depth += 1
    return ancestors


def find_relevant_decisions(file_path: str, context_root: Path, root: Path) -> list[dict]:
    """Find active decisions that reference the file, plus their ancestor constraints."""
    decisions_dir = context_root / "decisions"
    if not decisions_dir.exists():
        return []

    try:
        rel = str(Path(file_path).resolve().relative_to(root.resolve()))
    except ValueError:
        return []

    filename = Path(rel).name
    parent_dir = str(Path(rel).parent)
    patterns = [rel, filename]
    if parent_dir and parent_dir != ".":
        patterns.append(parent_dir + "/")

    graph = build_decision_graph(decisions_dir)
    direct_matches = []

    for dec_id, node in graph.items():
        if node["status"] in ("superseded", "deprecated", "rejected"):
            continue
        content = node["file"].read_text(errors="replace")
        if any(p in content for p in patterns):
            direct_matches.append({"id": dec_id, "title": node["title"], "status": node["status"], "depth": 0})

    results = []
    seen_ids = set()
    for match in direct_matches:
        if match["id"] not in seen_ids:
            results.append(match)
            seen_ids.add(match["id"])
        ancestors = walk_ancestors(match["id"], graph)
        for anc in ancestors:
            if anc["id"] not in seen_ids:
                results.append(anc)
                seen_ids.add(anc["id"])

    return results


def find_relevant_failure_todos(file_path: str, context_root: Path, root: Path) -> list[dict]:
    """Find open failure-todos that affect the file or its module."""
    ft_dir = context_root / "failure-todos"
    if not ft_dir.exists():
        return []

    try:
        rel = str(Path(file_path).resolve().relative_to(root.resolve()))
    except ValueError:
        return []

    resolved_statuses = {"resolved", "fixed", "wontfix"}
    results = []

    for ft_file in sorted(ft_dir.glob("ft-*.html")):
        status = read_meta(ft_file, "status")
        if status in resolved_statuses:
            continue
        affects = read_meta(ft_file, "affects")
        content = ft_file.read_text(errors="replace")
        if rel in content or (affects and any(part in rel for part in affects.split())):
            title = read_meta(ft_file, "title") or ft_file.stem
            results.append({"file": ft_file, "title": title, "status": status, "affects": affects})

    return results


def format_output(tracking_pages: list, decisions: list, failure_todos: list, context_root: Path) -> str:
    """Format all findings as a concise block for stderr injection."""
    lines = []

    if tracking_pages:
        lines.append("=== TRACKING PAGES ===")
        for page in tracking_pages:
            rel = page.relative_to(context_root)
            title = read_meta(page, "title") or page.stem
            reviewed = read_meta(page, "reviewed-at") or "never"
            lines.append(f"  {rel} ({title}) [reviewed: {reviewed}]")

    if decisions:
        lines.append("=== ACTIVE DECISIONS (constraints) ===")
        for dec in decisions:
            indent = "  " + "  " * dec.get("depth", 0)
            prefix = "→" if dec.get("depth", 0) == 0 else "↑"
            lines.append(f"{indent}{prefix} [{dec['status']}] {dec.get('id', '')}: {dec['title']}")

    if failure_todos:
        lines.append("=== OPEN FAILURE-TODOS ===")
        for ft in failure_todos:
            lines.append(f"  [{ft['status']}] {ft['title']}")
            if ft.get("affects"):
                lines.append(f"    affects: {ft['affects']}")

    if not lines:
        return ""

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: find-tracking-page.py <file_path>", file=sys.stderr)
        sys.exit(1)

    file_path = sys.argv[1]
    context_root = find_context_root()
    if not context_root:
        sys.exit(0)

    root = repo_root(context_root)
    reverse_index = build_reverse_index(context_root)

    tracking_pages = find_tracking_pages(file_path, reverse_index, root)
    decisions = find_relevant_decisions(file_path, context_root, root)
    failure_todos = find_relevant_failure_todos(file_path, context_root, root)

    output = format_output(tracking_pages, decisions, failure_todos, context_root)
    if output:
        print(output)


if __name__ == "__main__":
    main()
