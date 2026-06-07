#!/usr/bin/env python3
"""Validate all context/ invariants."""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from context_utils import check_reachability, find_context_root, read_config, read_meta, tracks_status


def html_files(context_root: Path):
    for html_file in sorted(context_root.rglob("*.html")):
        if "archived" in html_file.parts or "docs" in html_file.parts:
            continue
        yield html_file


def check_line_counts(context_root: Path, max_lines=200):
    failures = []
    for html_file in html_files(context_root):
        lines = len(html_file.read_text(errors="replace").splitlines())
        if lines > max_lines:
            failures.append(f"{html_file.name}: {lines} lines (max {max_lines})")
    return failures


def check_links(context_root: Path):
    failures = []
    for html_file in html_files(context_root):
        content = html_file.read_text(errors="replace")
        for match in re.finditer(r'href="(\./[^"#]+)"', content):
            href = match.group(1)
            target = (html_file.parent / href).resolve()
            if not target.exists():
                failures.append(f"{html_file.name} -> {href} (not found)")
    return failures


def check_lock_meta(context_root: Path):
    failures = []
    for html_file in sorted(context_root.glob("*.html")):
        if html_file.name == "index.html":
            continue
        content = html_file.read_text(errors="replace")
        if '<meta name="locked"' not in content:
            failures.append(f"{html_file.name}: missing <meta name=\"locked\">")
        if '<meta name="locked-by"' not in content:
            failures.append(f"{html_file.name}: missing <meta name=\"locked-by\">")
        if '<meta name="locked-at"' not in content:
            failures.append(f"{html_file.name}: missing <meta name=\"locked-at\">")
    return failures


def check_index_coverage(context_root: Path):
    failures = []
    index_path = context_root / "index.html"
    if not index_path.exists():
        return ["index.html does not exist"]
    index_content = index_path.read_text(errors="replace")
    for html_file in sorted(context_root.glob("*.html")):
        if html_file.name == "index.html":
            continue
        if html_file.name not in index_content:
            failures.append(f"{html_file.name}: not referenced in index.html")
    return failures


def check_decision_graph(context_root: Path):
    failures = []
    required_terms = {"Question", "Decision", "Rationale", "Consequences", "Review when"}
    decision_ids = set()
    for html_file in html_files(context_root):
        content = html_file.read_text(errors="replace")
        decision_ids.update(re.findall(r'id="(dec-\d+)"', content))
        for attrs, article_body in re.findall(r'<article\b([^>]*)>(.*?)</article>', content, flags=re.S):
            if not re.search(r'class="[^"]*\bdecision\b[^"]*"', attrs):
                continue
            id_match = re.search(r'id="([^"]+)"', attrs)
            decision_id = id_match.group(1) if id_match else f"{html_file.name}:unknown"
            if 'data-status="' not in attrs:
                failures.append(f"{html_file.name}: {decision_id} missing data-status")
            terms = set(re.findall(r'<dt>\s*([^<]+?)\s*</dt>', article_body, flags=re.S))
            for required in sorted(required_terms - terms):
                failures.append(f"{html_file.name}: {decision_id} missing decision field '{required}'")
    for html_file in html_files(context_root):
        content = html_file.read_text(errors="replace")
        for match in re.finditer(r'data-builds-on="([^"]+)"', content):
            for ref in [r.strip() for r in match.group(1).split(",")]:
                if ref and ref not in decision_ids:
                    failures.append(f"{html_file.name}: data-builds-on references unknown '{ref}'")
    return failures


def check_reachability_critical(context_root: Path):
    result = check_reachability(context_root)
    return [f"{item['from']} -> {item['to']}" for item in result.get("broken_links", [])]


def check_reachability_warnings(context_root: Path):
    result = check_reachability(context_root)
    warnings = []
    if result.get("fallback_root"):
        warnings.append(f"fallback root used: {result.get('root')}")
    for orphan in result.get("orphans", []):
        warnings.append(f"orphan page: {orphan}")
    return warnings


def active_lock_rows(ledger_content: str):
    match = re.search(r'<section id="active-locks">.*?<tbody>(.*?)</tbody>', ledger_content, flags=re.S)
    if not match:
        return []
    rows = []
    for row in re.findall(r'<tr>(.*?)</tr>', match.group(1), flags=re.S):
        cells = re.findall(r'<td>(.*?)</td>', row, flags=re.S)
        if len(cells) >= 2:
            rows.append((cells[0], cells[1]))
    return rows


def check_ledger_consistency(context_root: Path):
    failures = []
    ledger_path = context_root / "ledger.html"
    if not ledger_path.exists():
        return []
    ledger_content = ledger_path.read_text(errors="replace")
    locked_in_ledger = set(active_lock_rows(ledger_content))
    for page, agent in locked_in_ledger:
        page_path = context_root / page
        if not page_path.exists():
            failures.append(f"ledger lists {page} but file does not exist")
            continue
        if read_meta(page_path, "locked") != "true":
            failures.append(f"ledger lists {page} as locked but page meta is not true")
        locked_by = read_meta(page_path, "locked-by")
        if locked_by and locked_by != agent:
            failures.append(f"ledger lists {page} owner {agent} but page meta owner is {locked_by}")
    for page_path in sorted(context_root.glob("*.html")):
        if page_path.name == "index.html":
            continue
        if read_meta(page_path, "locked") == "true":
            owner = read_meta(page_path, "locked-by")
            if (page_path.name, owner) not in locked_in_ledger:
                failures.append(f"{page_path.name}: locked in meta but missing active ledger row")
    return failures


def check_tracks(context_root: Path):
    failures = []
    for html_file in sorted(context_root.glob("*.html")):
        if html_file.name == "index.html":
            continue
        tracking = tracks_status(html_file)
        if tracking["status"] == "malformed":
            failures.append(f"{html_file.name}: malformed tracks: {tracking['reason']}")
    return failures


def check_reviewed_at(context_root: Path):
    failures = []
    for html_file in sorted(context_root.glob("*.html")):
        value = read_meta(html_file, "reviewed-at")
        if not value:
            continue
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            failures.append(f"{html_file.name}: malformed reviewed-at '{value}'")
    return failures


def check_ledger_events(context_root: Path):
    failures = []
    ledger_path = context_root / "ledger.html"
    if not ledger_path.exists():
        return []
    content = ledger_path.read_text(errors="replace")
    if '<section id="events">' not in content:
        failures.append("ledger.html: missing <section id=\"events\">")
        return failures
    match = re.search(r'<section id="events">.*?<tbody>(.*?)</tbody>', content, flags=re.S)
    if not match:
        failures.append("ledger.html: events section missing table body")
        return failures
    for row in re.findall(r'<tr\b([^>]*)>(.*?)</tr>', match.group(1), flags=re.S):
        attrs, body = row
        for key in ["time", "event", "page", "agent", "status"]:
            if f"data-{key}=" not in attrs:
                failures.append(f"ledger.html: event row missing data-{key}")
        cells = re.findall(r'<td>.*?</td>', body, flags=re.S)
        if len(cells) != 6:
            failures.append("ledger.html: event row must have 6 cells")
    return failures


def check_config(context_root: Path):
    failures = []
    config_path = context_root / "config.json"
    if not config_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text(errors="replace"))
    except json.JSONDecodeError as e:
        return [f"config.json: invalid JSON: {e}"]
    ignore_tracks = config.get("ignoreTracks", [])
    if not isinstance(ignore_tracks, list) or not all(isinstance(item, str) for item in ignore_tracks):
        failures.append("config.json: ignoreTracks must be a list of strings")
    return failures


def main():
    parser = argparse.ArgumentParser(description="Validate context/ invariants")
    parser.add_argument("--fix", action="store_true", help="Reserved; no fixes in V1")
    args = parser.parse_args()

    context_root = find_context_root()
    if not context_root:
        print("ERROR: No context/ directory found")
        sys.exit(1)

    config = read_config(context_root)
    max_lines = int(config.get("maxLinesPerPage", 200))
    checks = {
        "line_counts": check_line_counts(context_root, max_lines),
        "links": check_links(context_root),
        "lock_meta": check_lock_meta(context_root),
        "index_coverage": check_index_coverage(context_root),
        "decision_graph": check_decision_graph(context_root),
        "ledger_consistency": check_ledger_consistency(context_root),
        "ledger_events": check_ledger_events(context_root),
        "tracks": check_tracks(context_root),
        "reviewed_at": check_reviewed_at(context_root),
        "config": check_config(context_root),
        "reachability": check_reachability_critical(context_root),
    }
    warnings = {
        "reachability": check_reachability_warnings(context_root),
    }

    all_pass = True
    for name, failures in checks.items():
        if failures:
            all_pass = False
            print(f"FAIL: {name}")
            for failure in failures:
                print(f"  - {failure}")
        else:
            print(f"PASS: {name}")
    for name, items in warnings.items():
        if items:
            print(f"WARN: {name}")
            for item in items:
                print(f"  - {item}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
