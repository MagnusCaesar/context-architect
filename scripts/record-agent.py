#!/usr/bin/env python3
"""Record advisory agent subtree state."""

import argparse
import html
import json
import os
import re
import sys
from collections import defaultdict

from context_utils import (
    agent_role,
    append_ledger_event,
    find_context_root,
    has_permission,
    now_utc,
    permission_denied,
    set_meta_in_content,
    write_atomic,
)


FIELDS = ["time", "agent", "parent", "role", "task", "page", "status", "details"]
LEDGER_STATUSES = {"spawned", "blocked", "handoff", "closed"}


def parse_attrs(attrs: str) -> dict:
    return {
        key: html.unescape(value)
        for key, value in re.findall(r'data-([A-Za-z0-9_-]+)="([^"]*)"', attrs)
    }


def read_records(content: str) -> dict:
    match = re.search(r'<section id="agent-rows">.*?<tbody>(.*?)</tbody>', content, flags=re.S)
    if not match:
        return {}
    records = {}
    for attrs, _body in re.findall(r'<tr\b([^>]*)>(.*?)</tr>', match.group(1), flags=re.S):
        row = parse_attrs(attrs)
        agent = row.get("agent", "")
        if agent:
            records[agent] = {field: row.get(field, "") for field in FIELDS}
    return records


def row_html(record: dict) -> str:
    attrs = " ".join(
        f'data-{field}="{html.escape(str(record.get(field, "")), quote=True)}"'
        for field in FIELDS
    )
    cells = "".join(f"<td>{html.escape(str(record.get(field, '')))}</td>" for field in FIELDS)
    return f"          <tr {attrs}>{cells}</tr>\n"


def tree_html(records: dict) -> str:
    children = defaultdict(list)
    for agent, record in records.items():
        parent = record.get("parent", "")
        if parent and parent in records:
            children[parent].append(agent)

    child_agents = {agent for values in children.values() for agent in values}
    roots = sorted(agent for agent in records if agent not in child_agents)

    def render_node(agent: str, depth: int = 5) -> str:
        record = records[agent]
        indent = " " * depth
        label = (
            f'<strong>{html.escape(agent)}</strong> '
            f'<span data-status="{html.escape(record.get("status", ""), quote=True)}">{html.escape(record.get("status", ""))}</span> '
            f'<span>{html.escape(record.get("role", ""))}</span> '
            f'<code>{html.escape(record.get("page", ""))}</code> '
            f'{html.escape(record.get("task", ""))}'
        )
        kids = sorted(children.get(agent, []))
        if not kids:
            return f"{indent}<li>{label}</li>\n"
        nested = "".join(render_node(child, depth + 4) for child in kids)
        return f"{indent}<li>{label}\n{indent}  <ul>\n{nested}{indent}  </ul>\n{indent}</li>\n"

    return "".join(render_node(agent) for agent in roots)


def render_agent_tree(content: str, records: dict) -> str:
    tree_rows = tree_html(records)
    table_rows = "".join(row_html(records[agent]) for agent in sorted(records))
    content = re.sub(
        r'(<section id="tree">.*?<ul class="agent-tree">\n)(.*?)(\s*</ul>)',
        rf"\1{tree_rows}\3",
        content,
        count=1,
        flags=re.S,
    )
    content = re.sub(
        r'(<section id="agent-rows">.*?<tbody>\n)(.*?)(\s*</tbody>)',
        rf"\1{table_rows}\3",
        content,
        count=1,
        flags=re.S,
    )
    return content


def main():
    parser = argparse.ArgumentParser(description="Record advisory agent subtree state")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--parent-id", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--page", default="")
    parser.add_argument("--status", choices=["spawned", "active", "blocked", "handoff", "closed"], required=True)
    parser.add_argument("--details", default="")
    parser.add_argument("--actor-id", default=os.environ.get("AGENT_ID", ""))
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print(json.dumps({"error": "No context/ directory found"}))
        sys.exit(1)

    actor_id = args.actor_id or args.agent_id
    if actor_id != args.agent_id and not has_permission(context_root, actor_id, "record_any_agent"):
        print(json.dumps(permission_denied(actor_id, "record_any_agent", agent_role(context_root, actor_id)), indent=2))
        sys.exit(1)

    path = context_root / "agent-tree.html"
    if not path.exists():
        print(json.dumps({"error": "agent-tree.html does not exist"}))
        sys.exit(1)

    content = path.read_text(errors="replace")
    records = read_records(content)
    previous = records.get(args.agent_id, {})
    records[args.agent_id] = {
        "time": now_utc(),
        "agent": args.agent_id,
        "parent": args.parent_id or previous.get("parent", ""),
        "role": args.role or previous.get("role", ""),
        "task": args.task or previous.get("task", ""),
        "page": args.page or previous.get("page", ""),
        "status": args.status,
        "details": args.details,
    }
    content = set_meta_in_content(render_agent_tree(content, records), "updated", now_utc()[:10])
    write_atomic(path, content, context_root=context_root)

    ledger_appended = args.status in LEDGER_STATUSES
    if ledger_appended:
        append_ledger_event(
            context_root,
            "agent_" + args.status,
            args.page or "agent-tree.html",
            actor_id,
            args.status,
            f"agent={args.agent_id} parent={args.parent_id} role={args.role} task={args.task} details={args.details}",
        )

    print(json.dumps({
        "status": "recorded",
        "agent": args.agent_id,
        "actor": actor_id,
        "agent_status": args.status,
        "ledger_appended": ledger_appended,
    }, indent=2))


if __name__ == "__main__":
    main()
