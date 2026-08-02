#!/usr/bin/env python3
"""Shared helpers for context-architecture scripts."""

from __future__ import annotations

import fnmatch
import html
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


CONTEXT_ONLY = "context-only"
_HYGIENE_RUNNING = False


class MutexTimeout(Exception):
    """Raised when context_mutex cannot be acquired within the configured ceiling."""
    pass
DEFAULT_PERMISSION_PROFILES = {
    "orchestrator": {
        "acquire_lock": True,
        "release_lock": True,
        "break_stale_lock": True,
        "force_release_lock": True,
        "update_tracks": True,
        "record_any_agent": True,
        "record_self": True,
    },
    "worker": {
        "acquire_lock": True,
        "release_lock": True,
        "break_stale_lock": False,
        "force_release_lock": False,
        "update_tracks": False,
        "record_any_agent": False,
        "record_self": True,
    },
    "readonly": {
        "acquire_lock": False,
        "release_lock": False,
        "break_stale_lock": False,
        "force_release_lock": False,
        "update_tracks": False,
        "record_any_agent": False,
        "record_self": False,
    },
}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def find_context_root() -> Path | None:
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "context" / "index.html").exists():
            return parent / "context"
    if (cwd / "index.html").exists():
        return cwd
    for parent in Path(__file__).resolve().parents:
        if (parent / "index.html").exists():
            return parent
    return None


def read_config(context_root: Path) -> dict:
    path = context_root / "config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError:
        return {}


def permission_profiles(context_root: Path) -> dict:
    config = read_config(context_root)
    profiles = config.get("permissionProfiles")
    if isinstance(profiles, dict):
        merged = {name: dict(values) for name, values in DEFAULT_PERMISSION_PROFILES.items()}
        for name, values in profiles.items():
            if isinstance(values, dict):
                merged[str(name)] = {**merged.get(str(name), {}), **values}
        return merged
    return DEFAULT_PERMISSION_PROFILES


def agent_role(context_root: Path, agent_id: str) -> str:
    config = read_config(context_root)
    roles = config.get("agentRoles", {})
    if isinstance(roles, dict) and agent_id in roles:
        return str(roles[agent_id])
    return str(config.get("defaultRole", "readonly"))


def has_permission(context_root: Path, agent_id: str, capability: str) -> bool:
    role = agent_role(context_root, agent_id)
    profile = permission_profiles(context_root).get(role, {})
    return profile.get(capability) is True


def permission_denied(agent_id: str, capability: str, role: str) -> dict:
    return {
        "status": "permission_denied",
        "allowed": False,
        "agent": agent_id,
        "role": role,
        "capability": capability,
        "reason": f"{role} cannot {capability}",
        "action": "orchestrator_resolution_required",
    }


def repo_root(context_root: Path) -> Path:
    config = read_config(context_root)
    roots = config.get("repoRoots", [])
    if roots:
        raw = Path(roots[0].get("path", "."))
        if not raw.is_absolute():
            raw = context_root.parent / raw
        return raw.resolve()
    return context_root.parent.resolve()


def resolve_context_page(context_root: Path, page: str, must_exist: bool = False) -> Path:
    raw = Path(page)
    if raw.is_absolute() or any(part == ".." for part in raw.parts):
        raise ValueError(f"invalid context page path: {page}")
    if raw.suffix != ".html":
        raise ValueError(f"context page must be .html: {page}")
    resolved = (context_root / raw).resolve()
    try:
        resolved.relative_to(context_root.resolve())
    except ValueError as exc:
        raise ValueError(f"context page escapes context root: {page}") from exc
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"{page} does not exist")
    return resolved


@contextmanager
def context_mutex(context_root: Path, name: str = "context"):
    # ponytail: bounded wait replaces the old unbounded LOCK_EX. A wedged holder
    # used to hang the waiter until the harness killed it ("No stderr output").
    # Ceiling from config lockMutexTimeoutSec (default 10s); on deadline raise
    # MutexTimeout so callers fail loud instead of hanging.
    import fcntl
    import time

    try:
        ceiling = float(read_config(context_root).get("lockMutexTimeoutSec", 10))
    except (TypeError, ValueError):
        ceiling = 10.0
    lock_dir = context_root / ".locks"
    lock_dir.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    lock_path = lock_dir / f"{safe_name}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + ceiling
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MutexTimeout(name)
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_meta(filepath: Path, name: str) -> str:
    content = filepath.read_text(errors="replace")
    match = re.search(rf'<meta\s+name="{re.escape(name)}"\s+content="([^"]*)"', content)
    return html.unescape(match.group(1)) if match else ""


def set_meta_in_content(content: str, name: str, value: str) -> str:
    escaped = html.escape(value, quote=True)
    pattern = rf'(<meta\s+name="{re.escape(name)}"\s+content=")[^"]*(")'
    if re.search(pattern, content):
        return re.sub(pattern, lambda m: f"{m.group(1)}{escaped}{m.group(2)}", content, count=1)
    insert = f'  <meta name="{name}" content="{escaped}">\n'
    if "</head>" in content:
        return content.replace("</head>", insert + "</head>", 1)
    return insert + content


def write_meta(filepath: Path, name: str, value: str, context_root: Path | None = None) -> None:
    content = filepath.read_text(errors="replace")
    write_atomic(filepath, set_meta_in_content(content, name, value), context_root=context_root)


def write_atomic(path: Path, content: str, context_root: Path | None = None) -> None:
    """Write by temp file in the same directory, then atomically replace."""
    path = Path(path)
    warn_dirty_target(path, context_root)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def warn_dirty_target(path: Path, context_root: Path | None = None) -> None:
    root = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(path.parent),
            timeout=3,
        )
        if result.returncode == 0:
            root = Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return
    if not root:
        return
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    try:
        status = subprocess.run(
            ["git", "status", "--short", "--", str(rel)],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=3,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return
    if status.returncode != 0 or not status.stdout.strip():
        return
    details = ""
    if context_root:
        latest = latest_ledger_event(context_root, page=path.name)
        if latest:
            details = f"; latest ledger event: {latest}"
    print(f"WARNING: rewriting dirty target {path}{details}", file=sys.stderr)


def parse_tracks(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def tracks_status(page_path: Path) -> dict:
    raw = read_meta(page_path, "tracks")
    tracks = parse_tracks(raw)
    if not tracks:
        return {"status": "untracked", "tracks": []}
    if tracks == [CONTEXT_ONLY]:
        return {"status": "context-only", "tracks": tracks}
    if CONTEXT_ONLY in tracks:
        return {"status": "malformed", "tracks": tracks, "reason": "context-only cannot be combined with file tracks"}
    return {"status": "tracked", "tracks": tracks}


def ignored(path: str, ignore_patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in ignore_patterns)


def match_tracks(files: list[str], tracks: list[str]) -> list[str]:
    matched = []
    for changed in files:
        if any(changed == track or fnmatch.fnmatch(changed, track) for track in tracks):
            matched.append(changed)
    return matched


def stale_tracks(tracks: list[str], root: Path, ignore_patterns: list[str] | None = None) -> list[str]:
    ignore_patterns = ignore_patterns or []
    stale = []
    for track in tracks:
        if track == CONTEXT_ONLY or ignored(track, ignore_patterns):
            continue
        if any(ch in track for ch in "*?["):
            if not list(root.glob(track)):
                stale.append(track)
        elif not (root / track).exists():
            stale.append(track)
    return stale


def ensure_ledger_events_section(content: str) -> str:
    if '<section id="events">' in content:
        return content
    section = """\n    <section id="events">\n      <h2>Events</h2>\n      <table>\n        <thead>\n          <tr><th>Time</th><th>Event</th><th>Page</th><th>Agent</th><th>Status</th><th>Details</th></tr>\n        </thead>\n        <tbody>\n        </tbody>\n      </table>\n    </section>\n"""
    if "</main>" in content:
        return content.replace("</main>", section + "  </main>", 1)
    return content + section


def ledger_events_path(context_root: Path) -> Path:
    return context_root / "ledger-events.ndjson"


def ledger_render_limit(context_root: Path) -> int:
    try:
        return int(read_config(context_root).get("ledgerRenderLimit", 75))
    except (TypeError, ValueError):
        return 75


def read_ledger_events(context_root: Path) -> list[dict]:
    path = ledger_events_path(context_root)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def append_ledger_event_record(context_root: Path, record: dict) -> None:
    path = ledger_events_path(context_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())


def ledger_event_row(record: dict) -> str:
    base = {
        "time": str(record.get("time", "")),
        "event": str(record.get("event", "")),
        "page": str(record.get("page", "")),
        "agent": str(record.get("agent", "")),
        "status": str(record.get("status", "")),
    }
    extra = record.get("extra_attrs") if isinstance(record.get("extra_attrs"), dict) else {}
    attrs = {**base, **{str(k): str(v) for k, v in extra.items()}}
    attr_text = " ".join(f'data-{key}="{html.escape(value, quote=True)}"' for key, value in attrs.items())
    cells = "".join(
        f"<td>{html.escape(str(value))}</td>"
        for value in [base["time"], base["event"], base["page"], base["agent"], base["status"], record.get("details", "")]
    )
    return f"          <tr {attr_text}>{cells}</tr>\n"


def render_ledger_events(context_root: Path) -> None:
    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return
    with context_mutex(context_root, "ledger"):
        content = ensure_ledger_events_section(ledger.read_text(errors="replace"))
        limit = ledger_render_limit(context_root)
        events = read_ledger_events(context_root)
        if limit > 0:
            events = events[-limit:]
        rows = "".join(ledger_event_row(record) for record in events)
        pattern = r'(<section id="events">.*?<tbody>\n)(.*?)(\s*</tbody>)'
        new_content, count = re.subn(pattern, lambda m: f"{m.group(1)}{rows}{m.group(3)}", content, count=1, flags=re.S)
        if count == 0:
            new_content = content.replace("</tbody>", rows + "        </tbody>", 1)
        if new_content != content:
            write_atomic(ledger, new_content, context_root=context_root)


def append_ledger_event(
    context_root: Path,
    event: str,
    page: str,
    agent: str,
    status: str,
    details: str = "",
    extra_attrs: dict[str, str] | None = None,
    trigger_hygiene: bool = True,
) -> None:
    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return
    if trigger_hygiene and event != "daily_hygiene":
        maybe_run_daily_hygiene(context_root)
    timestamp = now_utc()
    record = {
        "time": timestamp,
        "event": event,
        "page": page,
        "agent": agent,
        "status": status,
        "details": details,
    }
    if extra_attrs:
        record["extra_attrs"] = {str(k): str(v) for k, v in extra_attrs.items()}
    append_ledger_event_record(context_root, record)
    render_ledger_events(context_root)


def latest_ledger_event(context_root: Path, page: str = "") -> str:
    for record in reversed(read_ledger_events(context_root)):
        if page and str(record.get("page", "")) != page:
            continue
        event = str(record.get("event", ""))
        if event:
            return f"{record.get('time', '?')} {event} {record.get('status', '')}".strip()
    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return ""
    content = ledger.read_text(errors="replace")
    rows = re.findall(r'<tr\b([^>]*)>(.*?)</tr>', content, flags=re.S)
    for attrs, cells in reversed(rows):
        if 'data-event=' not in attrs:
            continue
        page_match = re.search(r'data-page="([^"]*)"', attrs)
        if page and page_match and page_match.group(1) != page:
            continue
        event = re.search(r'data-event="([^"]*)"', attrs)
        status = re.search(r'data-status="([^"]*)"', attrs)
        time = re.search(r'data-time="([^"]*)"', attrs)
        if event:
            return f"{time.group(1) if time else '?'} {event.group(1)} {status.group(1) if status else ''}".strip()
    return ""


def add_active_lock(context_root: Path, page: str, agent: str, purpose: str = "start-task") -> None:
    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return
    with context_mutex(context_root, "ledger"):
        content = ledger.read_text(errors="replace")
        row = (
            f'          <tr><td>{html.escape(page)}</td><td>{html.escape(agent)}</td>'
            f'<td>{now_utc()}</td><td>{html.escape(purpose)}</td></tr>\n'
        )
        pattern = r'(<section id="active-locks">.*?<tbody>)(.*?)(\s*</tbody>)'
        new_content, count = re.subn(pattern, lambda m: f"{m.group(1)}\n{m.group(2)}{row}{m.group(3)}", content, count=1, flags=re.S)
        if count == 0:
            new_content = content.replace("</tbody>", row + "        </tbody>", 1)
        write_atomic(ledger, new_content, context_root=context_root)


def remove_active_lock(context_root: Path, page: str, agent: str) -> None:
    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return
    with context_mutex(context_root, "ledger"):
        content = ledger.read_text(errors="replace")
        pattern = rf'\s*<tr><td>{re.escape(html.escape(page))}</td><td>{re.escape(html.escape(agent))}</td>.*?</tr>\n?'
        new_content = re.sub(pattern, "", content)
        write_atomic(ledger, new_content, context_root=context_root)


def validation_failure_summary(output: str, limit: int = 8) -> list[str]:
    lines = [line.rstrip() for line in output.splitlines()]
    failures = []
    keep = False
    for line in lines:
        if line.startswith("FAIL:"):
            keep = True
            failures.append(line)
            continue
        if line.startswith("PASS:"):
            keep = False
        elif keep and line.strip().startswith("-"):
            failures.append(line)
        if len(failures) >= limit:
            break
    return failures


def project_root(context_root: Path) -> Path:
    return context_root.parent


def rel_to_project(context_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root(context_root).resolve()))
    except ValueError:
        return str(path)


def live_context_pages(context_root: Path) -> set[str]:
    pages = set()
    for page in context_root.rglob("*.html"):
        if "docs" in page.parts or ".locks" in page.parts or "archived" in page.relative_to(context_root).parts:
            continue
        pages.add(rel_to_project(context_root, page))
    return pages


def select_reachability_root(context_root: Path) -> tuple[Path, str, bool, str]:
    root = project_root(context_root)
    candidates = [
        root / "AGENTS.md",
        root / "CLAUDE.md",
        root / ".agents" / "AGENTS.md",
        context_root / "index.html",
        context_root / "CONTEXT-MAP.html",
        context_root / "CONTEXT-MAP.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            rel = rel_to_project(context_root, candidate)
            return candidate, rel, rel.startswith("context/"), ""
    fallback = context_root / "index.html"
    return fallback, rel_to_project(context_root, fallback), True, "no bootloader root found"


def _normalize_context_target(context_root: Path, source: Path, target: str) -> str | None:
    target = target.strip()
    if not target or target.startswith("#"):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return None
    base = source.parent
    resolved = (base / target.split("#", 1)[0]).resolve()
    try:
        resolved.relative_to(context_root.resolve())
    except ValueError:
        return None
    return rel_to_project(context_root, resolved)


def _bootloader_edges(context_root: Path, root_file: Path) -> tuple[set[str], list[dict]]:
    edges: set[str] = set()
    broken = []
    text = root_file.read_text(errors="replace")
    for line in text.splitlines():
        for match in re.findall(r"context/[A-Za-z0-9_./-]+\.(?:html|md)", line):
            target = (project_root(context_root) / match).resolve()
            rel = rel_to_project(context_root, target)
            if target.exists():
                edges.add(rel)
            else:
                broken.append({"from": rel_to_project(context_root, root_file), "to": rel})
    return edges, broken


def _html_edges(context_root: Path, page: Path) -> tuple[set[str], list[dict]]:
    if page.name in ("ledger.html", "agent-tree.html"):
        return set(), []
    content = page.read_text(errors="replace")
    edges: set[str] = set()
    broken = []
    source_rel = rel_to_project(context_root, page)
    for href in re.findall(r'href=["\']([^"\']+)["\']', content):
        target_rel = _normalize_context_target(context_root, page, href)
        if not target_rel:
            continue
        target_path = project_root(context_root) / target_rel
        if target_path.exists():
            if target_path.suffix == ".html":
                edges.add(target_rel)
        else:
            broken.append({"from": source_rel, "to": target_rel})
    return edges, broken


def check_reachability(context_root: Path) -> dict:
    live_pages = live_context_pages(context_root)
    root_file, root_name, fallback_root, root_warning = select_reachability_root(context_root)
    edges: dict[str, set[str]] = {}
    broken_links: list[dict] = []

    if root_name.startswith("context/") and root_file.suffix == ".html":
        root_edges, root_broken = _html_edges(context_root, root_file)
    else:
        root_edges, root_broken = _bootloader_edges(context_root, root_file)
    edges[root_name] = root_edges
    broken_links.extend(root_broken)

    for rel in sorted(live_pages):
        page = project_root(context_root) / rel
        page_edges, page_broken = _html_edges(context_root, page)
        edges[rel] = page_edges
        broken_links.extend(page_broken)

    reachable = set()
    parent: dict[str, str | None] = {root_name: None}
    queue = [root_name]
    while queue:
        node = queue.pop(0)
        if node in reachable:
            continue
        reachable.add(node)
        for nxt in sorted(edges.get(node, set())):
            if nxt not in parent:
                parent[nxt] = node
            if nxt not in reachable:
                queue.append(nxt)

    orphans = sorted(live_pages - reachable)
    paths = {}
    for page in sorted(reachable & live_pages):
        cur = page
        chain = [cur]
        while parent.get(cur):
            cur = parent[cur]  # type: ignore[assignment]
            chain.append(cur)
        paths[page] = list(reversed(chain))

    status = "ok"
    if broken_links:
        status = "warning"
    if orphans:
        status = "orphans_found"
    if root_warning and status == "ok":
        status = "warning"

    handoff = None
    if orphans or broken_links:
        handoff = {
            "type": "context_hygiene_request",
            "reason": "unreachable context pages or broken links found",
            "candidates": [
                {
                    "path": path,
                    "recommended_actions": ["link_existing", "merge_into_page", "archive_candidate", "keep_with_reason"],
                }
                for path in orphans
            ],
            "broken_links": broken_links,
        }

    return {
        "status": status,
        "root": root_name,
        "fallback_root": fallback_root,
        "root_warning": root_warning,
        "reachable": sorted(reachable & live_pages),
        "paths": paths,
        "orphans": orphans,
        "broken_links": broken_links,
        "handoff_request": handoff,
    }


def daily_hygiene_ran_today(context_root: Path) -> bool:
    today = datetime.now().date()
    for record in read_ledger_events(context_root):
        if record.get("event") != "daily_hygiene":
            continue
        raw_time = str(record.get("time", ""))
        try:
            event_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if event_time.astimezone().date() == today:
                return True
        except ValueError:
            if raw_time.startswith(today.isoformat()):
                return True

    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return False
    content = ledger.read_text(errors="replace")
    for attrs, _body in re.findall(r'<tr\b([^>]*)>(.*?)</tr>', content, flags=re.S):
        if 'data-event="daily_hygiene"' in attrs:
            m = re.search(r'data-time="([^"]*)"', attrs)
            if not m:
                continue
            raw_time = m.group(1)
            try:
                event_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                if event_time.astimezone().date() == today:
                    return True
            except ValueError:
                if raw_time.startswith(today.isoformat()):
                    return True
    return False


def rotate_ledger_events(context_root: Path) -> dict:
    """Archive events from previous days into ledger-archive/YYYY-MM-DD.ndjson."""
    events_path = ledger_events_path(context_root)
    if not events_path.exists():
        return {"rotated": 0}
    today = datetime.now(timezone.utc).date().isoformat()
    archive_dir = context_root / "ledger-archive"
    archive_dir.mkdir(exist_ok=True)

    keep = []
    by_date: dict[str, list[str]] = {}
    for line in events_path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            keep.append(line)
            continue
        event_date = str(record.get("time", ""))[:10]
        if event_date == today:
            keep.append(line)
        else:
            by_date.setdefault(event_date, []).append(line)

    rotated = 0
    for date_str, lines in sorted(by_date.items()):
        archive_path = archive_dir / f"{date_str}.ndjson"
        with archive_path.open("a", encoding="utf-8") as f:
            for l in lines:
                f.write(l + "\n")
            f.flush()
            os.fsync(f.fileno())
        rotated += len(lines)

    if rotated > 0:
        with events_path.open("w", encoding="utf-8") as f:
            for l in keep:
                f.write(l + "\n")
            f.flush()
            os.fsync(f.fileno())
        render_ledger_events(context_root)

    return {"rotated": rotated, "kept": len(keep)}


def run_daily_hygiene(context_root: Path, append_event: bool = True) -> dict:
    if daily_hygiene_ran_today(context_root):
        return {"status": "skipped", "reason": "already_ran_today"}
    rotation = rotate_ledger_events(context_root)
    result = check_reachability(context_root)
    broken = len(result.get("broken_links", []))
    orphans = len(result.get("orphans", []))
    fallback = bool(result.get("fallback_root"))
    status = "ok"
    if broken:
        status = "critical"
    elif orphans or fallback:
        status = "warning"
    details = f"orphans={orphans} broken_links={broken} fallback_root={str(fallback).lower()} rotated={rotation.get('rotated', 0)}"
    if append_event:
        extra = {}
        if result.get("handoff_request"):
            extra["handoff"] = "context_hygiene_request"
        append_ledger_event(
            context_root,
            "daily_hygiene",
            "context",
            "system",
            status,
            details,
            extra_attrs=extra,
            trigger_hygiene=False,
        )
    return {"status": status, "reachability": result, "rotation": rotation}


def maybe_run_daily_hygiene(context_root: Path) -> None:
    global _HYGIENE_RUNNING
    if _HYGIENE_RUNNING or daily_hygiene_ran_today(context_root):
        return
    _HYGIENE_RUNNING = True
    try:
        run_daily_hygiene(context_root, append_event=True)
    finally:
        _HYGIENE_RUNNING = False


def write_intent(context_root: Path, page: str, agent_id: str, intent: str, blocked: bool = False) -> None:
    """Append agent intent to the intent registry. Used for contention resolution."""
    locks_dir = context_root / ".locks"
    locks_dir.mkdir(exist_ok=True)
    registry = locks_dir / "intents.ndjson"
    entry = json.dumps({
        "page": page,
        "agent": agent_id,
        "intent": intent,
        "blocked": blocked,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    with open(registry, "a") as f:
        f.write(entry + "\n")


def read_pending_contentions(context_root: Path) -> list[dict]:
    """Read unresolved contention events (blocked=true, no resolution yet)."""
    registry = context_root / ".locks" / "intents.ndjson"
    if not registry.exists():
        return []
    pending = []
    for line in registry.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("blocked") and not entry.get("resolved"):
            pending.append(entry)
    return pending


def resolve_contention(context_root: Path, page: str, agent_id: str, resolution: str) -> None:
    """Mark a contention event as resolved."""
    registry = context_root / ".locks" / "intents.ndjson"
    if not registry.exists():
        return
    lines = registry.read_text().splitlines()
    updated = []
    for line in lines:
        if not line.strip():
            updated.append(line)
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            updated.append(line)
            continue
        if entry.get("page") == page and entry.get("agent") == agent_id and entry.get("blocked"):
            entry["resolved"] = resolution
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
        updated.append(json.dumps(entry))
    registry.write_text("\n".join(updated) + "\n")


def clear_intents_for_page(context_root: Path, page: str) -> None:
    """Remove all intent entries for a page (called on lock release)."""
    registry = context_root / ".locks" / "intents.ndjson"
    if not registry.exists():
        return
    lines = registry.read_text().splitlines()
    kept = [l for l in lines if l.strip() and page not in l]
    registry.write_text("\n".join(kept) + "\n" if kept else "")


def write_pid_sentinel(context_root: Path, page: str) -> None:
    """Write owning process PID to a sentinel file alongside the lock."""
    locks_dir = context_root / ".locks"
    locks_dir.mkdir(exist_ok=True)
    sentinel = locks_dir / f"pid-{page.replace('/', '_')}"
    sentinel.write_text(str(os.getppid()))


def touch_heartbeat(context_root: Path, agent_id: str) -> None:
    """Touch heartbeat file for this agent. Called on every edit by the hook."""
    locks_dir = context_root / ".locks"
    locks_dir.mkdir(exist_ok=True)
    hb = locks_dir / f"hb-{agent_id}"
    hb.write_text(str(os.getpid()))


def remove_pid_sentinel(context_root: Path, page: str) -> None:
    """Remove PID sentinel on lock release."""
    sentinel = context_root / ".locks" / f"pid-{page.replace('/', '_')}"
    sentinel.unlink(missing_ok=True)


def _owner_process_alive(context_root: Path, page: str) -> bool:
    """Check if the process that acquired the lock is still running."""
    sentinel = context_root / ".locks" / f"pid-{page.replace('/', '_')}"
    if not sentinel.exists():
        return False
    try:
        pid = int(sentinel.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def _heartbeat_age_minutes(context_root: Path, agent_id: str) -> float | None:
    """Minutes since this agent's last heartbeat. None if no heartbeat exists."""
    hb = context_root / ".locks" / f"hb-{agent_id}"
    if not hb.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(hb.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - mtime).total_seconds() / 60
    except OSError:
        return None


def contention_break_allowed(context_root: Path, page: str, lock_owner: str) -> bool:
    """Can the lock be broken due to contention? True if owner's heartbeat is stale."""
    config = read_config(context_root)
    contention_minutes = float(config.get("contentionBreakMinutes", 3))

    # Check heartbeat staleness
    hb_age = _heartbeat_age_minutes(context_root, lock_owner)
    if hb_age is not None and hb_age > contention_minutes:
        return True

    # ponytail: dead-PID fast-break removed — pid sentinel stores getppid() (ephemeral shell), unreliable. Rely on heartbeat staleness. Upgrade path: store a persistent session id in the sentinel, then a real liveness check can return.
    return False


def reap_stale_locks(context_root: Path) -> list[dict]:
    """Release locks idle past the global timeout (1 day sanity cleanup).

    Single release trigger:
    - Global idle timeout (autoReleaseIdleMinutes, default 1440) using
      max(locked-at, page mtime, heartbeat mtime).

    The former dead-PID immediate-release trigger was removed (pid sentinel
    stores getppid(), unreliable). Contention-aware fast break is handled
    separately at lock-acquisition time (see contention_break_allowed).
    """
    config = read_config(context_root)
    idle_minutes = int(config.get("autoReleaseIdleMinutes", 1440))
    reaped = []

    ledger = context_root / "ledger.html"
    if not ledger.exists():
        return reaped

    content = ledger.read_text(errors="replace")
    match = re.search(r'<section id="active-locks">.*?<tbody>(.*?)</tbody>', content, flags=re.S)
    if not match:
        return reaped

    for row in re.findall(r'<tr>(.*?)</tr>', match.group(1), flags=re.S):
        cells = re.findall(r'<td>(.*?)</td>', row, flags=re.S)
        if len(cells) < 3:
            continue
        page, agent, locked_at_str = cells[0], cells[1], cells[2]

        # ponytail: dead-PID immediate-release removed — pid sentinel stores getppid() (ephemeral shell), so it reads "dead" for essentially every live lock and lets siblings steal it. Only the global idle timeout below reaps now. Upgrade path: store a persistent session id in the sentinel, then a real liveness check can return.
        # Global idle timeout
        if not locked_at_str:
            continue
        try:
            lock_time = datetime.fromisoformat(locked_at_str.replace("Z", "+00:00"))
            if lock_time.tzinfo is None:
                lock_time = lock_time.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        # Last activity = max(lock_time, page mtime, heartbeat mtime)
        activity_times = [lock_time]
        try:
            page_path = resolve_context_page(context_root, page)
            activity_times.append(datetime.fromtimestamp(page_path.stat().st_mtime, tz=timezone.utc))
        except (ValueError, FileNotFoundError, OSError):
            pass
        hb = context_root / ".locks" / f"hb-{agent}"
        if hb.exists():
            try:
                activity_times.append(datetime.fromtimestamp(hb.stat().st_mtime, tz=timezone.utc))
            except OSError:
                pass

        last_activity = max(activity_times)
        age_minutes = (datetime.now(timezone.utc) - last_activity).total_seconds() / 60
        if age_minutes <= idle_minutes:
            continue
        reason = "idle_timeout"

        page_path = resolve_context_page(context_root, page)
        if not page_path.exists():
            continue

        with context_mutex(context_root, f"lock-{page}"):
            page_content = page_path.read_text(errors="replace")
            page_content = set_meta_in_content(page_content, "locked", "false")
            page_content = set_meta_in_content(page_content, "locked-by", "")
            page_content = set_meta_in_content(page_content, "locked-at", "")
            write_atomic(page_path, page_content, context_root=context_root)
            remove_active_lock(context_root, page, agent)

        remove_pid_sentinel(context_root, page)
        append_ledger_event(
            context_root,
            "auto_release",
            page,
            "system",
            f"auto_released_{reason}",
            f"previous_owner={agent}",
            trigger_hygiene=False,
        )
        reaped.append({"page": page, "agent": agent, "reason": reason})

    return reaped
