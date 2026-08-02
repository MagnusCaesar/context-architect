#!/usr/bin/env python3
"""Check scoped unresolved failure todos before task close."""

import argparse
import fnmatch
import html
import json
import re
import sys
from pathlib import Path

from context_utils import find_context_root
from knowledge_graph import load_nodes


FAILURE_ID_RE = re.compile(r"^failure-\d{3}-[a-z0-9][a-z0-9-]*$")
FAILURE_STATUSES = {"open", "authorized", "blocked", "resolved", "deprecated"}
CURRENT_DECISION_STATUSES = {"accepted", "implemented"}


def emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def parse_attrs(raw: str) -> dict[str, str]:
    attrs = {}
    for match in re.finditer(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^>\s]+))""", raw):
        value = next(group for group in match.groups()[1:] if group is not None)
        attrs[match.group(1).lower()] = html.unescape(value)
    return attrs


def strip_tags(raw: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip()


def split_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def meta_values(content: str) -> dict[str, str]:
    values = {}
    for match in re.finditer(r"<meta\b([^>]*)>", content, flags=re.I):
        attrs = parse_attrs(match.group(1))
        name = attrs.get("name", "").lower()
        if name:
            values[name] = attrs.get("content", "")
    return values


def dl_value(body: str, name: str) -> str:
    pattern = rf"<dt[^>]*>\s*{re.escape(name)}\s*</dt>\s*<dd[^>]*>(.*?)</dd>"
    match = re.search(pattern, body, flags=re.I | re.S)
    if match:
        return strip_tags(match.group(1))
    pattern = rf"\b{re.escape(name)}\s*:\s*([^<\n]+)"
    match = re.search(pattern, strip_tags(body), flags=re.I)
    return match.group(1).strip() if match else ""


def attr_or_field(attrs: dict[str, str], meta: dict[str, str], body: str, field: str) -> str:
    return (
        attrs.get(f"data-{field}", "")
        or attrs.get(field, "")
        or meta.get(field, "")
        or dl_value(body, field)
    )


def has_named_section(body: str, name: str) -> bool:
    section = re.search(
        rf"<section\b[^>]*(?:id|class)=(?:\"[^\"]*{name}[^\"]*\"|'[^']*{name}[^']*')[^>]*>(.*?)</section>",
        body,
        flags=re.I | re.S,
    )
    if section and strip_tags(section.group(1)):
        return True
    heading = re.search(rf"<h[1-6][^>]*>\s*{name}\s*</h[1-6]>(.*?)(?:<h[1-6]\b|\Z)", body, flags=re.I | re.S)
    if heading and strip_tags(heading.group(1)):
        return True
    return bool(dl_value(body, name))


def failure_from_block(page: str, attrs: dict[str, str], meta: dict[str, str], body: str) -> dict | None:
    failure_id = attrs.get("id", "") or attrs.get("data-id", "") or meta.get("id", "")
    if not failure_id:
        return None
    status = attr_or_field(attrs, meta, body, "status").lower() or "open"
    return {
        "id": failure_id,
        "page": page,
        "status": status,
        "affects": split_list(attr_or_field(attrs, meta, body, "affects")),
        "topics": split_list(attr_or_field(attrs, meta, body, "topics")),
        "resolved_by": attr_or_field(attrs, meta, body, "resolved-by"),
        "blocked_by": attr_or_field(attrs, meta, body, "blocked-by"),
        "has_authorization": has_named_section(body, "authorization"),
    }


def parse_failures(context_root: Path) -> tuple[list[dict], list[str]]:
    paths = []
    router = context_root / "failure-todos.html"
    if router.exists():
        paths.append(router)
    node_dir = context_root / "failure-todos"
    if node_dir.exists():
        paths.extend(sorted(p for p in node_dir.glob("*.html") if "archived" not in p.parts))

    by_id: dict[str, dict] = {}
    invalid = []
    for path in paths:
        content = path.read_text(errors="replace")
        page = path.relative_to(context_root).as_posix()
        meta = meta_values(content)
        blocks = []
        if meta.get("id"):
            blocks.append(({}, content))
        for match in re.finditer(r"<(article|section|li|tr)\b([^>]*)>(.*?)</\1>", content, flags=re.I | re.S):
            attrs = parse_attrs(match.group(2))
            candidate = attrs.get("data-id", "") or attrs.get("id", "")
            if attrs.get("data-id", "").startswith("failure-") or FAILURE_ID_RE.match(candidate):
                blocks.append((attrs, match.group(3)))

        for attrs, body in blocks:
            record = failure_from_block(page, attrs, meta, body)
            if not record:
                continue
            if not FAILURE_ID_RE.match(record["id"]):
                invalid.append(record["id"])
                continue
            prior = by_id.get(record["id"], {})
            merged = {**prior, **{k: v for k, v in record.items() if v not in ("", [], False)}}
            merged["pages"] = sorted(set(prior.get("pages", []) + [page]))
            merged["has_authorization"] = prior.get("has_authorization", False) or record["has_authorization"]
            by_id[record["id"]] = merged
    for node in load_nodes(context_root):
        if node.kind != "failure" or node.archived:
            continue
        page = node.path.relative_to(context_root).as_posix()
        prior = by_id.get(node.node_id, {})
        by_id[node.node_id] = {
            **prior,
            "id": node.node_id,
            "page": page,
            "pages": sorted(set(prior.get("pages", []) + [page])),
            "status": node.status,
            "affects": list(node.affects),
            "topics": prior.get("topics", []),
            "has_authorization": prior.get("has_authorization", False),
        }
    return list(by_id.values()), sorted(set(invalid))


def parse_decisions(context_root: Path) -> dict[str, str]:
    return {node.node_id: node.status for node in load_nodes(context_root)
            if node.kind == "decision" and not node.archived}


def variants(value: str) -> set[str]:
    clean = value.strip().strip("/")
    if clean.startswith("./"):
        clean = clean[2:]
    values = {clean}
    if clean.startswith("context/"):
        values.add(clean.removeprefix("context/"))
    else:
        values.add(f"context/{clean}")
    return {v for v in values if v}


def overlaps(left: str, right: str) -> bool:
    for a in variants(left):
        for b in variants(right):
            if a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
                return True
    return False


def intersections(affects: list[str], scope: list[str]) -> list[str]:
    matched = []
    for affect in affects:
        if any(overlaps(affect, item) for item in scope):
            matched.append(affect)
    return sorted(set(matched))


def valid_authorization(record: dict, decisions: dict[str, str]) -> bool:
    resolver = record.get("resolved_by", "")
    if resolver and decisions.get(resolver) in CURRENT_DECISION_STATUSES:
        return True
    return bool(record.get("has_authorization"))


def check(context_root: Path, scope: list[str]) -> dict:
    failures, invalid_ids = parse_failures(context_root)
    decisions = parse_decisions(context_root)
    invalid_statuses = sorted({f"{f['id']}:{f.get('status', '')}" for f in failures if f.get("status") not in FAILURE_STATUSES})
    if invalid_ids or invalid_statuses:
        return {"status": "error", "invalid_failure_ids": invalid_ids, "invalid_statuses": invalid_statuses}

    blocked = []
    authorized = []
    unscoped = []
    for failure in failures:
        status = failure.get("status", "")
        if status in {"resolved", "deprecated"}:
            continue
        affects = failure.get("affects", [])
        if not affects:
            unscoped.append({"id": failure["id"], "status": status, "pages": failure.get("pages", [failure.get("page", "")])})
            continue
        related = intersections(affects, scope)
        if not related:
            continue
        item = {
            "id": failure["id"],
            "status": status,
            "affects": affects,
            "intersections": related,
            "pages": failure.get("pages", [failure.get("page", "")]),
        }
        if failure.get("resolved_by"):
            item["resolved_by"] = failure["resolved_by"]
        if failure.get("blocked_by"):
            item["blocked_by"] = failure["blocked_by"]
        if status in {"open", "blocked"}:
            blocked.append(item)
        elif status == "authorized":
            if valid_authorization(failure, decisions):
                authorized.append(item)
            else:
                item["reason"] = "authorized failure lacks current resolver or authorization section"
                blocked.append(item)

    status = "blocked_related_failure" if blocked else "warning_unscoped_failures" if unscoped else "clear"
    return {
        "status": status,
        "scope": scope,
        "blocked_failures": blocked,
        "authorized_warnings": authorized,
        "unscoped_failures": unscoped,
        "checked_failures": len(failures),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check failure todos for scoped blockers")
    parser.add_argument("--scope", action="append", default=[], help="Task scope path/glob/page; repeat or comma-separate")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        emit({"status": "error", "error": "No context/ directory found"})
        return 1
    scope = []
    for raw in args.scope:
        scope.extend(split_list(raw))
    result = check(context_root, sorted(set(scope)))
    emit(result)
    return 2 if result["status"] == "blocked_related_failure" else 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
