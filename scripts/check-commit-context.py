#!/usr/bin/env python3
"""Compare git commits with context metadata."""

import argparse
import fnmatch
import html
import json
import re
import subprocess
import sys
from pathlib import Path

from context_utils import find_context_root, ignored, match_tracks, read_config, repo_root, tracks_status
from knowledge_graph import load_nodes


COMMIT_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)


def emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def git(root: Path, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=timeout)


def git_text(root: Path, args: list[str]) -> str:
    result = git(root, args)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def parse_attrs(raw: str) -> dict[str, str]:
    attrs = {}
    for match in re.finditer(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^>\s]+))""", raw):
        value = next(group for group in match.groups()[1:] if group is not None)
        attrs[match.group(1).lower()] = html.unescape(value)
    return attrs


def strip_tags(raw: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip()


def meta_values(content: str) -> dict[str, str]:
    values = {}
    for match in re.finditer(r"<meta\b([^>]*)>", content, flags=re.I):
        attrs = parse_attrs(match.group(1))
        name = attrs.get("name", "").lower()
        if name:
            values[name] = attrs.get("content", "")
    return values


def split_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def read_recognition(context_root: Path) -> dict[str, str]:
    path = context_root / "recognized-commits.html"
    if not path.exists():
        return {"recognized_head": "", "recognized_range": ""}
    content = path.read_text(errors="replace")
    meta = meta_values(content)
    attrs = {}
    body = re.search(r"<body\b([^>]*)>", content, flags=re.I)
    if body:
        attrs.update(parse_attrs(body.group(1)))
    for match in re.finditer(r"<[^>]*\bdata-recognized-(?:head|range)\b[^>]*>", content, flags=re.I):
        attrs.update(parse_attrs(match.group(0)))
    return {
        "recognized_head": meta.get("recognized-head", "") or attrs.get("data-recognized-head", ""),
        "recognized_range": meta.get("recognized-range", "") or attrs.get("data-recognized-range", ""),
    }


def source_file(path: str) -> bool:
    return not (
        path.startswith("context/")
        or path.startswith("docs/context/")
        or path.startswith(".git/")
    )


def commit_list(root: Path, base: str, head: str) -> list[dict]:
    raw = git_text(root, ["log", "--format=%H%x00%s", f"{base}..{head}"])
    commits = []
    for line in raw.splitlines():
        if "\0" not in line:
            continue
        commit, subject = line.split("\0", 1)
        commits.append({"commit": commit, "subject": subject})
    return commits


def changed_files(root: Path, base: str, head: str) -> list[str]:
    raw = git_text(root, ["diff", "--name-only", base, head])
    return sorted(path for path in raw.splitlines() if path and source_file(path))


def commit_refs(context_root: Path) -> list[dict]:
    refs = []
    for path in sorted(context_root.rglob("*.html")):
        if "archived" in path.parts or "docs" in path.parts:
            continue
        page = path.relative_to(context_root).as_posix()
        content = path.read_text(errors="replace")
        meta = meta_values(content)
        meta_commits = sorted(set(COMMIT_RE.findall(meta.get("commits", ""))))
        if meta_commits:
            refs.append({"page": page, "node": "", "commits": meta_commits})
        for match in re.finditer(r"<(article|section|li|tr)\b([^>]*)>(.*?)</\1>", content, flags=re.I | re.S):
            attrs = parse_attrs(match.group(2))
            raw = ",".join(filter(None, [attrs.get("data-commit", ""), attrs.get("data-commits", "")]))
            commits = sorted(set(COMMIT_RE.findall(raw)))
            if commits:
                refs.append({"page": page, "node": attrs.get("id", "") or attrs.get("data-id", ""), "commits": commits})
    return refs


def ref_matches(commit: str, refs: set[str]) -> bool:
    return any(commit.startswith(ref.lower()) or ref.lower().startswith(commit) for ref in refs)


def dl_value(body: str, name: str) -> str:
    match = re.search(rf"<dt[^>]*>\s*{re.escape(name)}\s*</dt>\s*<dd[^>]*>(.*?)</dd>", body, flags=re.I | re.S)
    return strip_tags(match.group(1)) if match else ""


def affected_decisions(context_root: Path, files: list[str]) -> list[dict]:
    affected = []
    for node in load_nodes(context_root):
        if node.kind != "decision" or node.archived:
            continue
        matches = match_entries(files, list(node.affects))
        if matches:
            affected.append({
                "page": node.path.relative_to(context_root).as_posix(),
                "decision": node.node_id,
                "status": node.status,
                "affects": list(node.affects),
                "matched_files": matches,
            })
    return affected


def match_entries(files: list[str], patterns: list[str]) -> list[str]:
    matched = []
    for changed in files:
        if any(changed == pattern or fnmatch.fnmatch(changed, pattern) for pattern in patterns):
            matched.append(changed)
    return sorted(set(matched))


def matched_pages(context_root: Path, files: list[str]) -> tuple[list[dict], list[str]]:
    config = read_config(context_root)
    root = repo_root(context_root)
    ignore_patterns = config.get("ignoreTracks", [])
    matched = []
    seen = set()
    for page_path in sorted(context_root.rglob("*.html")):
        if "archived" in page_path.parts or "docs" in page_path.parts or page_path.name == "index.html":
            continue
        tracking = tracks_status(page_path)
        if tracking["status"] != "tracked":
            continue
        tracks = [track for track in tracking["tracks"] if not ignored(track, ignore_patterns)]
        matches = match_tracks(files, tracks)
        if matches:
            seen.update(matches)
            matched.append({
                "page": page_path.relative_to(context_root).as_posix(),
                "tracks": tracks,
                "matched_files": sorted(matches),
            })
    return matched, sorted(seen)


def base_from_range(raw: str) -> str:
    if ".." in raw:
        return raw.split("..", 1)[0].strip()
    return ""


def check(context_root: Path, from_ref: str = "", to_ref: str = "HEAD") -> dict:
    root = repo_root(context_root)
    if git(root, ["rev-parse", "--is-inside-work-tree"]).returncode != 0:
        return {"status": "unknown", "reason": "not a git repository"}

    head = git_text(root, ["rev-parse", to_ref])
    recognition = read_recognition(context_root)
    recognized_head = recognition["recognized_head"]
    recognized_range = recognition["recognized_range"]
    base = from_ref or recognized_head or base_from_range(recognized_range)
    if not base:
        return {
            "status": "needs_review",
            "head": head,
            "recognized_head": recognized_head,
            "recognized_range": recognized_range,
            "needs_review": True,
            "base_commit": "",
            "diff_range": "",
            "unrecognized_commits": [],
            "commit_refs": commit_refs(context_root),
            "changed_files": [],
            "matched_pages": [],
            "affected_decisions": [],
            "unmatched_files": [],
            "handoff_request": {"action": "review_commit_context", "reason": "no recognized head or range"},
        }
    try:
        base_commit = git_text(root, ["rev-parse", base])
    except RuntimeError:
        return {
            "status": "unknown",
            "head": head,
            "recognized_head": recognized_head,
            "recognized_range": recognized_range,
            "needs_review": True,
            "reason": "recognized base not found",
            "base_commit": base,
            "diff_range": f"{base}..{head}",
        }
    if git(root, ["merge-base", "--is-ancestor", base_commit, head]).returncode != 0:
        return {
            "status": "unknown",
            "head": head,
            "recognized_head": recognized_head,
            "recognized_range": recognized_range,
            "needs_review": True,
            "reason": "recognized base is not an ancestor of head",
            "base_commit": base_commit,
            "diff_range": f"{base_commit}..{head}",
        }

    files = changed_files(root, base_commit, head)
    refs = commit_refs(context_root)
    ref_hashes = {ref.lower() for item in refs for ref in item["commits"]}
    commits = commit_list(root, base_commit, head)
    unrecognized = [commit for commit in commits if not ref_matches(commit["commit"], ref_hashes)]
    pages, page_files = matched_pages(context_root, files)
    decisions = affected_decisions(context_root, files)
    decision_files = {file for item in decisions for file in item["matched_files"]}
    unmatched = sorted(set(files) - set(page_files) - decision_files)
    needs_review = bool(unrecognized or unmatched or decisions)
    handoff = None
    if needs_review:
        handoff = {
            "action": "review_commit_context",
            "range": f"{base_commit}..{head}",
            "unrecognized_commits": [item["commit"] for item in unrecognized],
            "unmatched_files": unmatched,
            "affected_decisions": [item["decision"] for item in decisions if item["decision"]],
        }
    return {
        "status": "needs_review" if needs_review else "ok",
        "head": head,
        "recognized_head": recognized_head,
        "recognized_range": recognized_range,
        "needs_review": needs_review,
        "base_commit": base_commit,
        "diff_range": f"{base_commit}..{head}",
        "unrecognized_commits": unrecognized,
        "commit_refs": refs,
        "changed_files": files,
        "matched_pages": pages,
        "affected_decisions": decisions,
        "unmatched_files": unmatched,
        "handoff_request": handoff,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check git commits against context metadata")
    parser.add_argument("--from", dest="from_ref", default="", help="Override recognized base")
    parser.add_argument("--to", dest="to_ref", default="HEAD", help="Git head/ref to check")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        emit({"status": "error", "error": "No context/ directory found"})
        return 1
    try:
        result = check(context_root, args.from_ref, args.to_ref)
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
    emit(result)
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
