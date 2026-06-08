#!/usr/bin/env python3
"""Ledger-backed source path claims for delegated source edits."""

import argparse
import fnmatch
import html
import json
import os
import re
import sys
from pathlib import Path

from context_utils import append_ledger_event, context_mutex, find_context_root, now_utc, set_meta_in_content, write_atomic


FIELDS = ["claim_id", "agent", "paths", "mode", "started_at", "expires_at", "reason"]


def emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def parse_attrs(raw: str) -> dict[str, str]:
    attrs = {}
    for match in re.finditer(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^>\s]+))""", raw):
        value = next(group for group in match.groups()[1:] if group is not None)
        attrs[match.group(1).lower()] = html.unescape(value)
    return attrs


def split_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def validate_paths(paths: list[str]) -> list[str]:
    clean = []
    for raw in paths:
        path = raw.strip().strip("/")
        if not path or path.startswith(".git/") or path.startswith("../") or path == ".." or "/../" in path or Path(path).is_absolute():
            raise ValueError(f"invalid path scope: {raw}")
        clean.append(path)
    return sorted(set(clean))


def safe_claim_id(agent: str) -> str:
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent).strip("-") or "agent"
    return f"claim-{now_utc().replace(':', '').replace('-', '')}-{safe_agent}-{os.getpid()}"


def static_prefix(pattern: str) -> str:
    pieces = re.split(r"[*?\[]", pattern, maxsplit=1)
    return pieces[0].rstrip("/")


def paths_overlap(left: str, right: str) -> bool:
    if left == right or fnmatch.fnmatch(left, right) or fnmatch.fnmatch(right, left):
        return True
    left_prefix = static_prefix(left)
    right_prefix = static_prefix(right)
    if left_prefix and right_prefix:
        return left_prefix.startswith(right_prefix + "/") or right_prefix.startswith(left_prefix + "/")
    return False


def claim_overlaps(claim: dict, paths: list[str]) -> bool:
    return any(paths_overlap(existing, requested) for existing in claim.get("paths", []) for requested in paths)


def compact_claim(claim: dict) -> dict:
    return {field: claim.get(field, [] if field == "paths" else "") for field in FIELDS}


def row_html(claim: dict) -> str:
    attrs = []
    for field in FIELDS:
        value = ",".join(claim.get(field, [])) if field == "paths" else str(claim.get(field, ""))
        attrs.append(f'data-{field.replace("_", "-")}="{html.escape(value, quote=True)}"')
    cells = "".join(
        f"<td>{html.escape(', '.join(claim.get(field, [])) if field == 'paths' else str(claim.get(field, '')))}</td>"
        for field in FIELDS
    )
    return f"          <tr {' '.join(attrs)}>{cells}</tr>\n"


def ensure_section(content: str) -> str:
    if '<section id="source-claims">' in content:
        return content
    section = """    <section id="source-claims">
      <h2>Active Source Claims</h2>
      <table>
        <thead>
          <tr><th>Claim</th><th>Agent</th><th>Paths</th><th>Mode</th><th>Started</th><th>Expires</th><th>Reason</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

"""
    if '    <section id="events">' in content:
        return content.replace('    <section id="events">', section + '    <section id="events">', 1)
    if '<section id="events">' in content:
        return content.replace('<section id="events">', section + '<section id="events">', 1)
    if "</main>" in content:
        return content.replace("</main>", section + "  </main>", 1)
    return content + "\n" + section


def parse_claims(content: str) -> list[dict]:
    match = re.search(r'<section id="source-claims">.*?<tbody>(.*?)</tbody>', content, flags=re.I | re.S)
    if not match:
        return []
    claims = []
    for row in re.finditer(r"<tr\b([^>]*)>(.*?)</tr>", match.group(1), flags=re.I | re.S):
        attrs = parse_attrs(row.group(1))
        claim = {
            "claim_id": attrs.get("data-claim-id", ""),
            "agent": attrs.get("data-agent", ""),
            "paths": split_list(attrs.get("data-paths", "")),
            "mode": attrs.get("data-mode", "exclusive") or "exclusive",
            "started_at": attrs.get("data-started-at", ""),
            "expires_at": attrs.get("data-expires-at", ""),
            "reason": attrs.get("data-reason", ""),
        }
        if claim["claim_id"]:
            claims.append(claim)
    return claims


def render_claims(content: str, claims: list[dict]) -> str:
    content = ensure_section(content)
    rows = "".join(row_html(claim) for claim in sorted(claims, key=lambda item: item.get("claim_id", "")))
    content = re.sub(
        r'(<section id="source-claims">.*?<tbody>\n?)(.*?)(\s*</tbody>)',
        lambda match: f"{match.group(1)}{rows}{match.group(3)}",
        content,
        count=1,
        flags=re.I | re.S,
    )
    return set_meta_in_content(content, "updated", now_utc()[:10])


def read_ledger(context_root: Path) -> tuple[Path, str, list[dict]]:
    path = context_root / "ledger.html"
    if not path.exists():
        raise FileNotFoundError("ledger.html does not exist")
    content = ensure_section(path.read_text(errors="replace"))
    return path, content, parse_claims(content)


def acquire(context_root: Path, args) -> dict:
    paths = validate_paths(args.paths)
    if args.mode != "exclusive":
        return {"status": "error", "error": "only exclusive mode is supported"}
    if not paths:
        return {"status": "error", "error": "--paths required"}
    if not args.reason:
        return {"status": "error", "error": "--reason required"}
    with context_mutex(context_root, "source-claims"):
        path, content, claims = read_ledger(context_root)
        duplicate = next((claim for claim in claims if claim["claim_id"] == args.claim_id), None) if args.claim_id else None
        if duplicate:
            return {"status": "error", "error": "claim_id already active", "claim_id": args.claim_id}
        overlaps = [compact_claim(claim) for claim in claims if claim.get("mode") == "exclusive" and claim_overlaps(claim, paths)]
        claim_id = args.claim_id or safe_claim_id(args.agent)
        if overlaps:
            append_ledger_event(
                context_root,
                "source_claim_blocked_overlap",
                "ledger.html",
                args.agent,
                "blocked_overlap",
                args.reason,
                {"claim_id": claim_id, "paths": ",".join(paths)},
            )
            return {"status": "blocked_overlap", "acquired": False, "claim_id": claim_id, "overlaps": overlaps}
        claim = {
            "claim_id": claim_id,
            "agent": args.agent,
            "paths": paths,
            "mode": args.mode,
            "started_at": now_utc(),
            "expires_at": args.expires_at or "",
            "reason": args.reason,
        }
        append_ledger_event(
            context_root,
            "source_claim_acquire",
            "ledger.html",
            args.agent,
            "acquired",
            args.reason,
            {"claim_id": claim_id, "paths": ",".join(paths), "mode": args.mode},
        )
        path, content, claims = read_ledger(context_root)
        claims = [item for item in claims if item["claim_id"] != claim_id]
        write_atomic(path, render_claims(content, claims + [claim]), context_root=context_root)
        return {"status": "acquired", "acquired": True, "claim": compact_claim(claim)}


def release(context_root: Path, args) -> dict:
    if not args.force and not args.reason:
        return {"status": "error", "error": "--reason required"}
    if args.force and not args.force_reason:
        return {"status": "error", "error": "--force requires --force-reason"}
    with context_mutex(context_root, "source-claims"):
        path, _content, claims = read_ledger(context_root)
        claim = next((item for item in claims if item["claim_id"] == args.claim_id), None)
        if not claim:
            return {"status": "not_found", "released": False, "claim_id": args.claim_id}
        if claim["agent"] != args.agent and not args.force:
            append_ledger_event(
                context_root,
                "source_claim_release_denied",
                "ledger.html",
                args.agent,
                "release_denied_wrong_owner",
                f"owned by {claim['agent']}",
                {"claim_id": args.claim_id},
            )
            return {"status": "release_denied_wrong_owner", "released": False, "claim": compact_claim(claim)}

        event = "source_claim_force_release" if args.force else "source_claim_release"
        details = args.force_reason if args.force else args.reason or "source claim released"
        append_ledger_event(
            context_root,
            event,
            "ledger.html",
            args.agent,
            "released",
            details,
            {"claim_id": args.claim_id, "previous_agent": claim["agent"]},
        )
        path, content, claims = read_ledger(context_root)
        remaining = [item for item in claims if item["claim_id"] != args.claim_id]
        write_atomic(path, render_claims(content, remaining), context_root=context_root)
        return {"status": "released", "released": True, "forced": bool(args.force), "claim": compact_claim(claim)}


def check(context_root: Path, args) -> dict:
    paths = validate_paths(args.paths) if args.paths else []
    _path, _content, claims = read_ledger(context_root)
    if paths:
        overlaps = [compact_claim(claim) for claim in claims if claim.get("mode") == "exclusive" and claim_overlaps(claim, paths)]
        return {"status": "blocked_overlap" if overlaps else "clear", "paths": paths, "overlaps": overlaps}
    return {"status": "ok", "active_claims": [compact_claim(claim) for claim in claims]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage active source claims")
    sub = parser.add_subparsers(dest="command", required=True)

    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--agent", "--agent-id", dest="agent", default=os.environ.get("AGENT_ID", ""))
    acquire_parser.add_argument("--paths", action="append", default=[])
    acquire_parser.add_argument("--claim-id", default="")
    acquire_parser.add_argument("--mode", default="exclusive", choices=["exclusive"])
    acquire_parser.add_argument("--expires-at", default="")
    acquire_parser.add_argument("--reason", required=True)

    release_parser = sub.add_parser("release")
    release_parser.add_argument("--agent", "--agent-id", dest="agent", default=os.environ.get("AGENT_ID", ""))
    release_parser.add_argument("--claim-id", required=True)
    release_parser.add_argument("--reason", default="")
    release_parser.add_argument("--force", action="store_true")
    release_parser.add_argument("--force-reason", default="")

    check_parser = sub.add_parser("check")
    check_parser.add_argument("--paths", action="append", default=[])

    args = parser.parse_args()
    if hasattr(args, "paths"):
        args.paths = split_list(",".join(args.paths))
    if hasattr(args, "agent") and not args.agent:
        emit({"status": "error", "error": "--agent required"})
        return 1

    context_root = find_context_root()
    if not context_root:
        emit({"status": "error", "error": "No context/ directory found"})
        return 1
    try:
        if args.command == "acquire":
            result = acquire(context_root, args)
        elif args.command == "release":
            result = release(context_root, args)
        else:
            result = check(context_root, args)
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
    emit(result)
    return 1 if result["status"] == "error" else 2 if result["status"] == "blocked_overlap" else 0


if __name__ == "__main__":
    raise SystemExit(main())
