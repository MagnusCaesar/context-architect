#!/usr/bin/env python3
"""Maintain the Active Work / Open Questions lifecycle graph."""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

from context_utils import (
    agent_role,
    append_ledger_event,
    canonical_context_root,
    context_mutex,
    has_permission,
    now_utc,
    permission_denied,
    read_config,
    set_meta_in_content,
    write_atomic,
)


TASK_ID = re.compile(r"AW-[0-9]+\Z", re.I)
QUESTION_ID = re.compile(r"OQ-[0-9]+\Z", re.I)
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TERMINAL = {"accepted", "rejected", "cancelled"}
TASK_STATES = {"untriaged", "ready", "in-progress", "verified", "awaiting-captain", "accepted", "rejected", "blocked", "deferred", "done"}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def meta(text: str, name: str) -> str:
    match = re.search(rf'<meta\s+name="{re.escape(name)}"\s+content="([^"]*)"', text)
    return html.unescape(match.group(1)) if match else ""


def valid_id(value: str, question: bool = False) -> str:
    pattern = QUESTION_ID if question else TASK_ID
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {'question' if question else 'task'} ID: {value}")
    return value.upper()


def safe_slug(value: str) -> str:
    if not SLUG.fullmatch(value):
        raise ValueError(f"invalid slug: {value}")
    return value


def page_path(root: Path, directory: str, node_id: str) -> Path:
    node_id = valid_id(node_id, question=directory == "open-questions")
    folder = lifecycle_dir(root, directory)
    matches = sorted(folder.glob(f"{node_id.lower()}-*.html")) if folder.is_dir() else []
    if len(matches) != 1 or matches[0].is_symlink():
        raise ValueError(f"expected one safe {directory} page for {node_id}; found {len(matches)}")
    result = matches[0].resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"{node_id} page escapes context root")
    return result


def lifecycle_dir(root: Path, directory: str) -> Path:
    folder = root / directory
    if folder.is_symlink() or not folder.resolve().is_relative_to(root.resolve()) or not folder.is_dir():
        raise ValueError(f"missing or unsafe lifecycle directory: {folder}")
    return folder


def checked_link(root: Path, source_page: Path, item: str) -> str:
    if "|" not in item:
        raise ValueError(f"link must be LABEL|HREF: {item}")
    label, href = item.split("|", 1)
    parsed_url = urlsplit(href)
    if not label.strip() or not href or any(ord(char) < 32 for char in href):
        raise ValueError(f"unsafe link: {href}")
    if parsed_url.scheme:
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username or parsed_url.password:
            raise ValueError(f"unsafe link: {href}")
    else:
        parsed = Path(parsed_url.path)
        if parsed.is_absolute():
            raise ValueError(f"link escapes context root: {href}")
        target = (source_page.parent / parsed).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ValueError(f"link escapes context root: {href}")
    return f'<a href="{esc(href)}">{esc(label.strip())}</a>'


def records(directory: Path, id_meta: str) -> list[dict]:
    result = []
    if directory.is_symlink():
        raise ValueError(f"symlink lifecycle directory: {directory}")
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*.html")):
        if path.is_symlink():
            raise ValueError(f"symlink in lifecycle directory: {path}")
        text = path.read_text(errors="replace")
        node_id = meta(text, id_meta)
        if node_id:
            result.append({"id": node_id, "path": path, "text": text})
    return result


def _replace_rows(content: str, marker: str, rows: str, managed: str) -> str:
    if marker not in content:
        raise ValueError(f"missing router marker: {marker}")
    content = re.sub(rf'<tr\b[^>]*data-lifecycle="{re.escape(managed)}"[^>]*>.*?</tr>\s*', "", content, flags=re.S)
    return content.replace(marker, marker + ("\n" + rows.rstrip() if rows else ""), 1)


def render_active(root: Path, content: str, overrides: dict[Path, str] | None = None) -> str:
    overrides = overrides or {}
    tasks = records(root / "active-work", "task-id")
    known = {record["path"] for record in tasks}
    for path, text in overrides.items():
        if path.parent == root / "active-work" and meta(text, "task-id"):
            if path in known:
                next(record for record in tasks if record["path"] == path)["text"] = text
            else:
                tasks.append({"id": meta(text, "task-id"), "path": path, "text": text})
    for head in re.findall(r'data-auto-head="(AW-H[1-4])"', content):
        rows = []
        for task in tasks:
            status, parent = meta(task["text"], "status"), meta(task["text"], "parent")
            if parent != head or status in TERMINAL | {"deferred"}:
                continue
            title = meta(task["text"], "title").split(": ", 1)[-1]
            rows.append(f'<li><a href="./active-work/{esc(task["path"].name)}">{esc(task["id"])}</a> — {esc(title)} <em>({esc(status)})</em></li>')
        pattern = rf'(<ul data-auto-head="{head}">).*?(</ul>)'
        replacement = "\n".join(rows) or "<li>No active child tasks.</li>"
        content, count = re.subn(pattern, lambda m: f'{m.group(1)}\n{replacement}\n{m.group(2)}', content, count=1, flags=re.S)
        if count != 1:
            raise ValueError(f"missing auto-head marker for {head}")
    return content


def render_question_router(root: Path, content: str, overrides: dict[Path, str] | None = None) -> str:
    overrides = overrides or {}
    rows = []
    questions = records(root / "open-questions", "question-id")
    known = {record["path"] for record in questions}
    for path, text in overrides.items():
        if path.parent == root / "open-questions" and meta(text, "question-id"):
            if path in known:
                next(record for record in questions if record["path"] == path)["text"] = text
            else:
                questions.append({"id": meta(text, "question-id"), "path": path, "text": text})
    for question in questions:
        qid, text = question["id"], question["text"]
        if meta(text, "status") not in {"blocking", "parked"}:
            continue
        task = page_path(root, "active-work", meta(text, "blocks"))
        rows.append(f'<tr data-lifecycle="question-{esc(qid)}"><td><a href="./open-questions/{esc(question["path"].name)}">{esc(qid)}</a></td><td>{esc(meta(text, "ask"))}</td><td>{esc(meta(text, "owner"))}</td><td><a href="./active-work/{esc(task.name)}">{esc(meta(text, "blocks"))}</a></td><td>{esc(meta(text, "contingency"))}</td></tr>')
    for old in re.findall(r'<tr\b[^>]*data-lifecycle="question-[^"]+"[^>]*>.*?</tr>', content, re.S):
        content = content.replace(old, "", 1)
    if "<!-- CAPTAIN-QUESTION-ROWS -->" not in content:
        raise ValueError("open-questions router lacks CAPTAIN-QUESTION-ROWS marker")
    return content.replace("<!-- CAPTAIN-QUESTION-ROWS -->", "<!-- CAPTAIN-QUESTION-ROWS -->\n" + "\n".join(rows), 1)


def preflight(root: Path, paths: list[Path]) -> dict[Path, str]:
    result = {}
    for path in paths:
        parents = path.parents
        has_symlink_parent = any(parent.is_symlink() for parent in parents if parent != root and parent.is_relative_to(root))
        if path.is_symlink() or has_symlink_parent or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"required lifecycle page missing or unsafe: {path}")
        result[path] = path.read_text(errors="replace")
    return result


def commit(root: Path, actor: str, event: str, page: str, updates: dict[Path, str], status: str, details: str = "") -> None:
    previous = {path: path.read_text(errors="replace") if path.exists() else None for path in updates}
    written = []
    try:
        for path, content in updates.items():
            write_atomic(path, content, context_root=root)
            written.append(path)
        append_ledger_event(root, "task_" + event, page, actor, status, details)
    except Exception:
        rollback_errors = []
        for path in reversed(written):
            try:
                if previous[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, previous[path], context_root=root)
            except OSError as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise RuntimeError(f"lifecycle rollback failed for {len(rollback_errors)} page(s)") from rollback_errors[0]
        raise


def authorize(root: Path, actor: str, disposition: bool = False, confirmed: bool = False) -> None:
    config = read_config(root)
    roles = config.get("agentRoles", {})
    if not isinstance(roles, dict) or actor not in roles:
        raise PermissionError(str(permission_denied(actor, "record_self", "readonly")))
    if not has_permission(root, actor, "record_self"):
        raise PermissionError(str(permission_denied(actor, "record_self", agent_role(root, actor))))
    if disposition and (actor != "captain" or not confirmed):
        raise PermissionError("captain disposition requires --actor-id captain --confirm-captain")


def operation_pages(root: Path, args: argparse.Namespace) -> list[Path]:
    pages = [root / "active-work.html"]
    if args.cmd == "new-task":
        pages.append(lifecycle_dir(root, "active-work") / f"{valid_id(args.task_id).lower()}-{safe_slug(args.slug)}.html")
    elif args.cmd == "new-question":
        pages += [page_path(root, "active-work", args.task), root / "open-questions.html"]
        pages.append(lifecycle_dir(root, "open-questions") / f"{valid_id(args.question_id, True).lower()}-{safe_slug(args.slug)}.html")
    elif args.cmd in {"answer-question", "defer-question"}:
        question = page_path(root, "open-questions", args.question_id)
        pages += [question, page_path(root, "active-work", meta(question.read_text(errors="replace"), "blocks")), root / "open-questions.html"]
        if args.cmd == "answer-question":
            pages.extend([root / "open-questions" / "archive.html", root / "future-workstreams.html"])
        else:
            pages.append(root / "future-workstreams.html")
    elif args.cmd == "archive-task":
        pages += [page_path(root, "active-work", args.task_id), root / "active-work" / "archive.html"]
    else:
        pages.append(root / "open-questions.html")
    return pages


def hold_page_locks(root: Path, actor: str, pages: list[Path]) -> ExitStack:
    stack = ExitStack()
    ordered = sorted({path for path in pages}, key=lambda path: path.relative_to(root).as_posix())
    for path in ordered:
        relative = path.relative_to(root).as_posix()
        stack.enter_context(context_mutex(root, f"lock-{relative}"))
        if path.exists():
            text = path.read_text(errors="replace")
            if meta(text, "locked") == "true" and meta(text, "locked-by") != actor:
                stack.close()
                raise PermissionError(f"{relative} is locked by {meta(text, 'locked-by') or 'another actor'}")
    return stack


def task_html(root: Path, args: argparse.Namespace) -> str:
    path = root / "active-work" / f"{args.task_id.lower()}-{args.slug}.html"
    source = " · ".join(checked_link(root, path, x) for x in args.source)
    decisions = " · ".join(checked_link(root, path, x) for x in args.decision) or "—"
    failures = " · ".join(checked_link(root, path, x) for x in args.failure) or "—"
    deps = []
    for dep in args.depends_on:
        dep_path = page_path(root, "active-work", dep)
        deps.append(f'<a href="./{esc(dep_path.name)}">{esc(valid_id(dep))}</a>')
    blockers = []
    for blocker in args.blocked_by:
        if QUESTION_ID.fullmatch(blocker):
            qpath = page_path(root, "open-questions", blocker)
            blockers.append(f'<a href="../open-questions/{esc(qpath.name)}">{esc(blocker.upper())}</a>')
        else:
            blockers.append(esc(blocker))
    body = f'''<dl><dt>State</dt><dd>{esc(args.status)}</dd><dt>Parent</dt><dd><a href="../active-work.html#{esc(args.parent.lower())}">{esc(args.parent)}</a></dd><dt>Source IDs</dt><dd>{esc(args.source_ids)}</dd><dt>Evidence</dt><dd>{source or "—"}</dd><dt>Depends on</dt><dd>{" · ".join(deps) or "—"}</dd><dt>Blocked by</dt><dd>{" · ".join(blockers) or "—"}</dd><dt>Decisions</dt><dd>{decisions}</dd><dt>Failure nodes</dt><dd>{failures}</dd><dt>Verify</dt><dd>{esc(args.verify)}</dd><dt>Contingency</dt><dd>{esc(args.contingency)}</dd></dl>'''
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="title" content="{esc(args.task_id)}: {esc(args.title)}"><meta name="summary" content="{esc(args.summary)}"><meta name="visibility" content="agent"><meta name="created" content="{now_utc()[:10]}"><meta name="updated" content="{now_utc()[:10]}"><meta name="status" content="{esc(args.status)}"><meta name="task-id" content="{esc(args.task_id)}"><meta name="parent" content="{esc(args.parent)}"><meta name="source-ids" content="{esc(args.source_ids)}"><meta name="depends-on" content="{esc(",".join(args.depends_on))}"><meta name="blocked-by" content="{esc(",".join(args.blocked_by))}"><meta name="owner" content="{esc(args.owner)}"><meta name="decision-ids" content="{esc(",".join(x.split("|",1)[0] for x in args.decision))}"><meta name="failure-ids" content="{esc(",".join(x.split("|",1)[0] for x in args.failure))}"><meta name="locked" content="false"><meta name="locked-by" content=""><meta name="locked-at" content=""><meta name="read-when" content="Selecting or updating this active work task"><meta name="update-when" content="Its state, edge, evidence, verification, or disposition changes"><meta name="tracks" content="context-only"></head><body><article id="{esc(args.task_id)}" data-statement="{esc(args.summary)}"><header><h1>{esc(args.task_id)}: {esc(args.title)}</h1><p class="summary">{esc(args.summary)}</p></header><main>{body}</main><footer><a href="../active-work.html">Active Work</a> · <a href="../open-questions.html">Open Questions</a></footer></article></body></html>'''


def new_task(root: Path, args: argparse.Namespace) -> None:
    args.task_id = valid_id(args.task_id)
    args.parent = args.parent.upper()
    if args.parent not in {f"AW-H{i}" for i in range(1, 5)}:
        raise ValueError(f"parent must be an Active Work head: {args.parent}")
    args.slug = safe_slug(args.slug)
    args.depends_on = [valid_id(item) for item in args.depends_on]
    args.blocked_by = [valid_id(item, True) if item.upper().startswith("OQ-") else item for item in args.blocked_by]
    if args.task_id in {f"AW-H{i}" for i in range(1, 5)}:
        raise ValueError("task ID cannot use a reserved Active Work head ID")
    if args.status not in TASK_STATES - TERMINAL:
        raise ValueError("invalid task status")
    task_dir = lifecycle_dir(root, "active-work")
    path = task_dir / f"{args.task_id.lower()}-{args.slug}.html"
    if path.exists():
        raise ValueError(f"task exists: {path.name}")
    for blocker in args.blocked_by:
        if QUESTION_ID.fullmatch(blocker):
            page_path(root, "open-questions", blocker)
    for dep in args.depends_on:
        page_path(root, "active-work", dep)
    updates = preflight(root, [root / "active-work.html"])
    updates[path] = task_html(root, args)
    updates[root / "active-work.html"] = render_active(root, updates[root / "active-work.html"], updates)
    commit(root, args.actor_id, "created", path.relative_to(root).as_posix(), updates, args.status, args.title)


def question_html(root: Path, args: argparse.Namespace, task: Path) -> str:
    links = " · ".join(checked_link(root, root / "open-questions" / f"{args.question_id.lower()}-{args.slug}.html", x) for x in args.source) or "—"
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="title" content="{esc(args.question_id)}: {esc(args.title)}"><meta name="ask" content="{esc(args.ask)}"><meta name="visibility" content="agent"><meta name="created" content="{now_utc()[:10]}"><meta name="updated" content="{now_utc()[:10]}"><meta name="status" content="{esc(args.status)}"><meta name="question-id" content="{esc(args.question_id)}"><meta name="owner" content="{esc(args.owner)}"><meta name="blocks" content="{esc(args.task)}"><meta name="contingency" content="{esc(args.contingency)}"><meta name="locked" content="false"><meta name="locked-by" content=""><meta name="locked-at" content=""><meta name="read-when" content="Answering or updating this human question"><meta name="update-when" content="Its answer, owner, blocker, contingency, or deferral changes"><meta name="tracks" content="context-only"></head><body><article id="{esc(args.question_id)}" data-statement="{esc(args.ask)}"><header><h1>{esc(args.question_id)}: {esc(args.title)}</h1><p class="summary">Human input required before the linked task can proceed.</p></header><main><dl><dt>State</dt><dd>{esc(args.status)}</dd><dt>Ask</dt><dd>{esc(args.ask)}</dd><dt>Owner</dt><dd>{esc(args.owner)}</dd><dt>Blocks</dt><dd><a href="../active-work/{esc(task.name)}">{esc(args.task)}</a></dd><dt>Contingency</dt><dd>{esc(args.contingency)}</dd><dt>Source</dt><dd>{links}</dd></dl></main><footer><a href="../open-questions.html">Open Questions</a> · <a href="../active-work.html">Active Work</a></footer></article></body></html>'''


def new_question(root: Path, args: argparse.Namespace) -> None:
    args.question_id = valid_id(args.question_id, True)
    args.task = valid_id(args.task)
    args.slug = safe_slug(args.slug)
    if args.status not in {"blocking", "parked"}:
        raise ValueError("invalid question status")
    allowed_owners = read_config(root).get("questionOwners", ["captain", "external"])
    if args.owner not in allowed_owners:
        raise ValueError(f"invalid question owner: {args.owner}")
    task = page_path(root, "active-work", args.task)
    if args.status == "blocking" and meta(task.read_text(errors="replace"), "status") in TERMINAL:
        raise ValueError(f"cannot add a blocking question to terminal task {args.task}")
    question = lifecycle_dir(root, "open-questions") / f"{args.question_id.lower()}-{args.slug}.html"
    if question.exists():
        raise ValueError(f"question exists: {question.name}")
    task_text = task.read_text(errors="replace")
    blocked_by = [x for x in meta(task_text, "blocked-by").split(",") if x]
    if args.status == "blocking" and args.question_id not in blocked_by:
        blocked_by.append(args.question_id)
    updates = preflight(root, [task, root / "active-work.html", root / "open-questions.html"])
    if args.status == "blocking":
        if meta(task_text, "status") != "blocked":
            updates[task] = set_meta_in_content(updates[task], "resume-status", meta(task_text, "status"))
        elif not meta(task_text, "resume-status"):
            updates[task] = set_meta_in_content(updates[task], "resume-status", "blocked")
        updates[task] = set_meta_in_content(updates[task], "status", "blocked")
        updates[task] = set_meta_in_content(updates[task], "blocked-by", ",".join(blocked_by))
        updates[task] = re.sub(r"(<dt>State</dt><dd>).*?(</dd>)", r"\g<1>blocked\g<2>", updates[task], count=1)
    updates[question] = question_html(root, args, task)
    updates[root / "active-work.html"] = render_active(root, updates[root / "active-work.html"], updates)
    updates[root / "open-questions.html"] = render_question_router(root, updates[root / "open-questions.html"], updates)
    commit(root, args.actor_id, "question_created", question.relative_to(root).as_posix(), updates, args.status, args.ask)


def question_update(root: Path, args: argparse.Namespace, action: str) -> None:
    qid = valid_id(args.question_id, True)
    question = page_path(root, "open-questions", qid)
    qtext = question.read_text(errors="replace")
    task = page_path(root, "active-work", meta(qtext, "blocks"))
    task_status = meta(task.read_text(errors="replace"), "status")
    if action == "defer" and task_status in TERMINAL:
        raise ValueError(f"cannot defer a question on terminal task {meta(qtext, 'blocks')}")
    paths = [question, task, root / "active-work.html", root / "open-questions.html"]
    if action == "defer":
        paths.append(root / "future-workstreams.html")
    if action == "answer":
        paths.extend([root / "open-questions" / "archive.html", root / "future-workstreams.html"])
    updates = preflight(root, paths)
    status = "answered" if action == "answer" else "deferred"
    qtext = set_meta_in_content(updates[question], "status", status)
    qtext = set_meta_in_content(qtext, "updated", now_utc()[:10])
    if action == "answer":
        section = f'<section id="answer"><h2>Answer</h2><p>{esc(args.answer)}</p></section>'
        pattern = r'<section id="answer">.*?</section>'
        qtext = re.sub(pattern, lambda _match: section, qtext, count=1, flags=re.S) if re.search(pattern, qtext, re.S) else qtext.replace("</main>", section + "</main>", 1)
    qtext = re.sub(r"(<dt>State</dt><dd>).*?(</dd>)", rf"\g<1>{status}\g<2>", qtext, count=1)
    updates[question] = qtext
    blocked = [x for x in meta(updates[task], "blocked-by").split(",") if x and x != qid]
    updates[task] = set_meta_in_content(updates[task], "blocked-by", ",".join(blocked))
    blocked_html = []
    for blocker in blocked:
        if QUESTION_ID.fullmatch(blocker):
            blocker_path = page_path(root, "open-questions", blocker)
            blocked_html.append(f'<a href="../open-questions/{esc(blocker_path.name)}">{esc(blocker)}</a>')
        else:
            blocked_html.append(esc(blocker))
    updates[task] = re.sub(r"(<dt>Blocked by</dt><dd>).*?(</dd>)", lambda m: f'{m.group(1)}{" · ".join(blocked_html) or "—"}{m.group(2)}', updates[task], count=1)
    related_questions = records(root / "open-questions", "question-id")
    deferred = [item for item in related_questions if item["id"] != qid and meta(item["text"], "blocks") == meta(qtext, "blocks") and meta(item["text"], "status") == "deferred"]
    if meta(qtext, "status") == "deferred":
        deferred.append({"id": qid})
    if task_status in TERMINAL:
        next_status = task_status
    elif blocked:
        next_status = "blocked"
    elif deferred:
        next_status = "deferred"
    else:
        next_status = meta(updates[task], "resume-status") or ("ready" if meta(updates[task], "status") in {"blocked", "deferred"} else meta(updates[task], "status"))
    if next_status == "deferred" and meta(updates[task], "status") != "deferred" and not meta(updates[task], "resume-status"):
        updates[task] = set_meta_in_content(updates[task], "resume-status", meta(updates[task], "status"))
    updates[task] = set_meta_in_content(updates[task], "status", next_status)
    if not blocked and not deferred:
        updates[task] = set_meta_in_content(updates[task], "resume-status", "")
    updates[task] = re.sub(r"(<dt>State</dt><dd>).*?(</dd>)", lambda m: f"{m.group(1)}{esc(next_status)}{m.group(2)}", updates[task], count=1)
    updates[task] = set_meta_in_content(updates[task], "updated", now_utc()[:10])
    updates[root / "active-work.html"] = render_active(root, updates[root / "active-work.html"], updates)
    updates[root / "open-questions.html"] = render_question_router(root, updates[root / "open-questions.html"], updates)
    if action == "answer":
        archive = updates[root / "open-questions" / "archive.html"]
        row = f'<tr data-lifecycle="answered-{esc(qid)}"><td><a href="./{esc(question.name)}">{esc(qid)}</a></td><td>answered</td><td>{now_utc()[:10]}</td><td>{esc(args.answer)}</td></tr>'
        archive = re.sub(rf'<tr\b[^>]*data-lifecycle="answered-{re.escape(qid)}"[^>]*>.*?</tr>\s*', "", archive, flags=re.S)
        if "<!-- QUESTION-ARCHIVE-ROWS -->" not in archive:
            raise ValueError("question archive lacks QUESTION-ARCHIVE-ROWS marker")
        updates[root / "open-questions" / "archive.html"] = archive.replace("<!-- QUESTION-ARCHIVE-ROWS -->", "<!-- QUESTION-ARCHIVE-ROWS -->\n" + row, 1)
        future = updates[root / "future-workstreams.html"]
        updates[root / "future-workstreams.html"] = re.sub(rf'<article\b[^>]*data-lifecycle="deferred-{re.escape(qid)}"[^>]*>.*?</article>\s*', "", future, flags=re.S)
    if action == "defer":
        future = updates[root / "future-workstreams.html"]
        if "<!-- DEFERRED-QUESTION-ROWS -->" not in future:
            raise ValueError("future-workstreams lacks DEFERRED-QUESTION-ROWS marker")
        task_name = task.name
        article = f'<article data-lifecycle="deferred-{esc(qid)}" id="deferred-{esc(qid.lower())}"><h3>{esc(qid)}: {esc(meta(qtext, "ask"))}</h3><p><strong>Activation trigger:</strong> {esc(args.trigger)}. <strong>Contingency:</strong> {esc(meta(qtext, "contingency"))}. <a href="./open-questions/{esc(question.name)}">Question</a> · <a href="./active-work/{esc(task_name)}">Affected task</a></p></article>'
        future = re.sub(rf'<article\b[^>]*data-lifecycle="deferred-{re.escape(qid)}"[^>]*>.*?</article>\s*', "", future, flags=re.S)
        updates[root / "future-workstreams.html"] = future.replace("<!-- DEFERRED-QUESTION-ROWS -->", "<!-- DEFERRED-QUESTION-ROWS -->\n" + article, 1)
    commit(root, args.actor_id, action + "_question", question.relative_to(root).as_posix(), updates, status, args.answer if action == "answer" else args.trigger)


def archive_task(root: Path, args: argparse.Namespace) -> None:
    task_id = valid_id(args.task_id)
    task = page_path(root, "active-work", task_id)
    text = task.read_text(errors="replace")
    if args.final == "accepted" and meta(text, "status") not in {"verified", "awaiting-captain"}:
        raise ValueError("captain acceptance requires a verified or awaiting-captain task")
    paths = [task, root / "active-work.html", root / "active-work" / "archive.html"]
    updates = preflight(root, paths)
    content = set_meta_in_content(updates[task], "status", args.final)
    content = set_meta_in_content(content, "updated", now_utc()[:10])
    content = re.sub(r"(<dt>State</dt><dd>).*?(</dd>)", rf"\g<1>{args.final}\g<2>", content, count=1)
    section = f'<section id="archive"><h2>Archive</h2><p>Captain disposition: {esc(args.note)}.</p></section>'
    content = re.sub(r'<section id="archive">.*?</section>', lambda _match: section, content, count=1, flags=re.S) if 'id="archive"' in content else content.replace("</main>", section + "</main>", 1)
    updates[task] = content
    updates[root / "active-work.html"] = render_active(root, updates[root / "active-work.html"], updates)
    archive = updates[root / "active-work" / "archive.html"]
    row = f'<tr data-lifecycle="task-{esc(task_id)}"><td><a href="./{esc(task.name)}">{esc(task_id)}</a></td><td>{esc(meta(text, "title").split(": ", 1)[-1])}</td><td>{args.final}</td><td>{now_utc()[:10]}</td><td>{esc(args.note)}</td></tr>'
    archive = re.sub(rf'<tr\b[^>]*data-lifecycle="task-{re.escape(task_id)}"[^>]*>.*?</tr>\s*', "", archive, flags=re.S)
    if "<!-- TASK-ARCHIVE-ROWS -->" not in archive:
        raise ValueError("task archive lacks TASK-ARCHIVE-ROWS marker")
    commit(root, args.actor_id, "disposition", task.relative_to(root).as_posix(), updates, args.final, args.note)


def ready(root: Path) -> None:
    tasks = records(root / "active-work", "task-id")
    states = {r["id"]: meta(r["text"], "status") for r in tasks}
    for record in tasks:
        text = record["text"]
        deps = [x for x in meta(text, "depends-on").split(",") if x]
        if meta(text, "status") == "ready" and not meta(text, "blocked-by") and all(states.get(dep) in {"done", "verified", "accepted"} for dep in deps):
            print(f'{record["id"]}\t{meta(text, "title")}\t{record["path"].relative_to(root)}')


def captain_questions(root: Path) -> None:
    owners = read_config(root).get("questionOwners", ["captain", "external"])
    for record in records(root / "open-questions", "question-id"):
        text = record["text"]
        if meta(text, "owner") in owners and meta(text, "status") in {"blocking", "parked"}:
            print(f'{record["id"]}\towner={meta(text, "owner")}\t{meta(text, "ask")}\tblocks={meta(text, "blocks")}\tcontingency={meta(text, "contingency")}')


def validate_lifecycle(context_root: Path) -> list[str]:
    """Return lifecycle graph defects for validate.py."""
    errors = []
    root = Path(context_root).resolve()
    if not any((root / name).exists() for name in ("active-work.html", "open-questions.html", "active-work", "open-questions")):
        return []
    tasks = records(root / "active-work", "task-id")
    questions = records(root / "open-questions", "question-id")
    question_ids = {meta(record["text"], "question-id") for record in questions}
    allowed_owners = read_config(root).get("questionOwners", ["captain", "external"])
    router_text = (root / "active-work.html").read_text(errors="replace") if (root / "active-work.html").is_file() else ""
    archive_text = (root / "active-work" / "archive.html").read_text(errors="replace") if (root / "active-work" / "archive.html").is_file() else ""
    ids = set()
    dependencies: dict[str, list[str]] = {}
    for record in tasks:
        task_id = meta(record["text"], "task-id")
        try:
            valid_id(task_id)
        except ValueError:
            errors.append(f"invalid active-work task ID in {record['path'].name}: {task_id}")
        if task_id in ids:
            errors.append(f"duplicate active-work task ID: {task_id}")
        ids.add(task_id)
        deps = [item for item in meta(record["text"], "depends-on").split(",") if item]
        dependencies[task_id] = deps
        for dep in deps:
            try:
                page_path(root, "active-work", dep)
            except ValueError as exc:
                errors.append(f"invalid dependency for {task_id}: {exc}")
        if meta(record["text"], "status") not in TASK_STATES:
            errors.append(f"invalid task status for {task_id}: {meta(record['text'], 'status')}")
        if meta(record["text"], "parent") not in {f"AW-H{i}" for i in range(1, 5)}:
            errors.append(f"invalid parent for {task_id}: {meta(record['text'], 'parent')}")
        for blocker in [item for item in meta(record["text"], "blocked-by").split(",") if item]:
            if blocker.upper().startswith("OQ-") and blocker not in question_ids:
                errors.append(f"unknown blocking question for {task_id}: {blocker}")
    qids = set()
    for record in questions:
        qid = meta(record["text"], "question-id")
        try:
            valid_id(qid, True)
            page_path(root, "active-work", meta(record["text"], "blocks"))
        except ValueError as exc:
            errors.append(f"invalid question {qid}: {exc}")
        if qid in qids:
            errors.append(f"duplicate open-question ID: {qid}")
        qids.add(qid)
        qstatus = meta(record["text"], "status")
        owner = meta(record["text"], "owner")
        if qstatus not in {"blocking", "parked", "answered", "deferred"}:
            errors.append(f"invalid question status for {qid}: {qstatus}")
        if owner not in allowed_owners:
            errors.append(f"invalid question owner for {qid}: {owner}")
        task = next((item for item in tasks if item["id"] == meta(record["text"], "blocks")), None)
        if qstatus == "blocking" and task and meta(task["text"], "status") not in TERMINAL and (qid not in meta(task["text"], "blocked-by").split(",") or meta(task["text"], "status") != "blocked"):
            errors.append(f"blocking question {qid} is not reflected on {task['id']}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            errors.append(f"active-work dependency cycle at {task_id}")
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies.get(task_id, []):
            if dependency in dependencies:
                visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)
    for record in tasks:
        task_id, status = record["id"], meta(record["text"], "status")
        active = f'./active-work/{record["path"].name}' in router_text
        archived = f'data-lifecycle="task-{task_id}"' in archive_text
        if status in TERMINAL and (active or not archived):
            errors.append(f"terminal task {task_id} must be archived and absent from active router")
        elif status not in TERMINAL | {"deferred"} and not active:
            errors.append(f"active task {task_id} is missing from active router")
    for filepath, marker in [(root / "active-work.html", 'data-auto-head="AW-H1"'), (root / "open-questions.html", "CAPTAIN-QUESTION-ROWS")]:
        if not filepath.is_file() or marker not in filepath.read_text(errors="replace"):
            errors.append(f"lifecycle router missing marker {marker}")
    return errors


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Maintain Active Work and Open Questions")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render"); sub.add_parser("ready"); sub.add_parser("questions")
    t = sub.add_parser("new-task")
    for name in ("task-id", "slug", "title", "summary", "parent", "status", "source-ids", "verify", "contingency"):
        t.add_argument("--" + name, required=True, choices=tuple(TASK_STATES - TERMINAL) if name == "status" else None)
    for name in ("source", "depends-on", "blocked-by", "decision", "failure"):
        t.add_argument("--" + name, action="append", default=[])
    t.add_argument("--owner", default="agent")
    q = sub.add_parser("new-question")
    for name in ("question-id", "slug", "title", "task", "ask", "owner", "contingency"):
        q.add_argument("--" + name, required=True)
    q.add_argument("--source", action="append", default=[]); q.add_argument("--status", choices=("blocking", "parked"), default="blocking")
    a = sub.add_parser("answer-question"); a.add_argument("--question-id", required=True); a.add_argument("--answer", required=True)
    d = sub.add_parser("defer-question"); d.add_argument("--question-id", required=True); d.add_argument("--trigger", required=True)
    c = sub.add_parser("archive-task"); c.add_argument("--task-id", required=True); c.add_argument("--final", choices=tuple(TERMINAL), required=True); c.add_argument("--note", required=True); c.add_argument("--confirm-captain", action="store_true")
    for command in sub.choices.values():
        command.add_argument("--actor-id", default=os.environ.get("AGENT_ID", "orchestrator"))
    return p


def main() -> None:
    args = parser().parse_args()
    try:
        root = canonical_context_root(Path.cwd())
        if (root / ".locks").is_symlink() or ((root / ".locks").exists() and not (root / ".locks").resolve().is_relative_to(root)):
            raise ValueError("unsafe lifecycle lock directory")
        if args.cmd in {"new-task", "new-question", "answer-question", "defer-question", "archive-task", "render"}:
            authorize(root, args.actor_id, args.cmd == "archive-task", getattr(args, "confirm_captain", False))
            # ponytail: serialize lifecycle writes; split by graph if contention matters.
            with context_mutex(root, "task-lifecycle"):
                page_locks = hold_page_locks(root, args.actor_id, operation_pages(root, args))
                with page_locks:
                    if args.cmd == "render":
                        updates = preflight(root, [root / "active-work.html", root / "open-questions.html"])
                        updates[root / "active-work.html"] = render_active(root, updates[root / "active-work.html"])
                        updates[root / "open-questions.html"] = render_question_router(root, updates[root / "open-questions.html"])
                        if any(path.read_text(errors="replace") != value for path, value in updates.items()):
                            commit(root, args.actor_id, "rendered", "active-work.html", updates, "rendered")
                    else:
                        {"new-task": lambda: new_task(root, args), "new-question": lambda: new_question(root, args), "answer-question": lambda: question_update(root, args, "answer"), "defer-question": lambda: question_update(root, args, "defer"), "archive-task": lambda: archive_task(root, args)}[args.cmd]()
        elif args.cmd == "ready":
            ready(root)
        elif args.cmd == "questions":
            captain_questions(root)
    except (ValueError, PermissionError, OSError) as exc:
        print(f"task-lifecycle: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
