#!/usr/bin/env python3
"""
Bootstrap a context/ architecture for any project.

Scans the repository, identifies key files/patterns, and generates
a complete context/ skeleton with index, ledger, decisions page,
config, and scripts.

Usage:
    python <skill_dir>/scripts/bootstrap.py --target /path/to/project
    python <skill_dir>/scripts/bootstrap.py --target . --scan
    python <skill_dir>/scripts/bootstrap.py --target . --config config.json

Modes:
    --scan      Scan repo and print findings (no file creation)
    --generate  Generate skeleton from scan results + config
    (default)   Interactive: scan → present → generate
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from context_utils import resolve_context_page, today_utc, write_atomic


SKILL_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"


def load_permission_defaults() -> dict:
    path = TEMPLATES_DIR / "permission-profiles.json"
    try:
        return json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def scan_repo(target: Path) -> dict:
    """Scan repository and return structured findings."""
    findings = {
        "root": str(target),
        "languages": Counter(),
        "key_files": [],
        "directories": [],
        "entry_points": [],
        "config_files": [],
        "test_files": [],
        "doc_files": [],
        "total_files": 0,
        "total_lines": 0,
        "git_info": {},
    }

    # Git info
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-20"],
            capture_output=True, text=True, cwd=str(target), timeout=5
        )
        if result.returncode == 0:
            findings["git_info"]["recent_commits"] = len(result.stdout.strip().split("\n"))
            findings["git_info"]["has_git"] = True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        findings["git_info"]["has_git"] = False

    # File scan
    ignore_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv",
                   "dist", "build", ".next", "coverage", ".tox", "env"}
    ignore_exts = {".pyc", ".pyo", ".o", ".so", ".dylib", ".class", ".jar"}

    for item in target.rglob("*"):
        if any(d in item.parts for d in ignore_dirs):
            continue
        if item.is_dir():
            rel = item.relative_to(target)
            if len(rel.parts) <= 2:
                findings["directories"].append(str(rel))
            continue
        if item.suffix in ignore_exts:
            continue

        findings["total_files"] += 1
        ext = item.suffix.lower()
        if ext:
            findings["languages"][ext] += 1

        rel_path = str(item.relative_to(target))

        # Categorize
        try:
            lines = len(item.read_text(errors="replace").splitlines())
            findings["total_lines"] += lines
        except (OSError, UnicodeDecodeError):
            lines = 0

        # Entry points
        if item.name in ("main.py", "app.py", "index.js", "index.ts", "main.go",
                         "Makefile", "docker-compose.yml", "Dockerfile"):
            findings["entry_points"].append({"path": rel_path, "lines": lines})

        # Config files
        if item.name in ("package.json", "pyproject.toml", "setup.py", "setup.cfg",
                         "Cargo.toml", "go.mod", "requirements.txt", "Pipfile",
                         ".env.example", "tsconfig.json", "webpack.config.js"):
            findings["config_files"].append(rel_path)

        # Test files
        if "test" in item.name.lower() or "spec" in item.name.lower():
            findings["test_files"].append(rel_path)

        # Doc files
        if item.suffix.lower() in (".md", ".rst", ".txt") and item.name.lower() not in ("license",):
            findings["doc_files"].append(rel_path)

        # Large/important files (>200 lines, not tests)
        if lines > 200 and "test" not in rel_path.lower():
            findings["key_files"].append({"path": rel_path, "lines": lines, "ext": ext})

    # Sort key files by size
    findings["key_files"].sort(key=lambda f: f["lines"], reverse=True)
    findings["key_files"] = findings["key_files"][:20]  # Top 20

    # Convert Counter to dict for JSON
    findings["languages"] = dict(findings["languages"].most_common(10))

    return findings


def generate_suggested_pages(findings: dict) -> list:
    """From scan findings, suggest context pages."""
    pages = []

    # Always include these structural pages
    pages.append({"name": "index.html", "purpose": "Root entry point and page map", "auto": True})
    pages.append({"name": "control-plane.html", "purpose": "Runtime workflow checklist", "auto": True})
    pages.append({"name": "ledger.html", "purpose": "Concurrency locks and history", "auto": True})
    pages.append({"name": "agent-tree.html", "purpose": "Advisory agent coordination tree", "auto": True})
    pages.append({"name": "decisions.html", "purpose": "Decision graph and rationale", "auto": True})

    # Suggest based on findings
    if findings["key_files"]:
        # Group by directory
        dirs = defaultdict(list)
        for f in findings["key_files"]:
            parts = Path(f["path"]).parts
            if len(parts) > 1:
                dirs[parts[0]].append(f)
            else:
                dirs["root"].append(f)

        for dir_name, files in dirs.items():
            if dir_name == "root":
                for f in files[:3]:
                    stem = Path(f["path"]).stem
                    pages.append({
                        "name": f"{stem}.html",
                        "purpose": f"Architecture/design of {f['path']}",
                        "source": f["path"],
                    })
            else:
                pages.append({
                    "name": f"{dir_name}.html",
                    "purpose": f"Architecture of {dir_name}/ subsystem ({len(files)} key files)",
                    "sources": [f["path"] for f in files],
                })

    # Domain glossary if project is non-trivial
    if findings["total_lines"] > 1000:
        pages.append({"name": "domain-glossary.html", "purpose": "Domain-specific terminology"})

    # Data formats if there are data files
    data_exts = {".csv", ".json", ".yaml", ".yml", ".xml", ".parquet"}
    if any(ext in findings["languages"] for ext in data_exts):
        pages.append({"name": "data-formats.html", "purpose": "Data file schemas and formats"})

    return pages


def doc_import_candidates(target: Path, findings: dict) -> list:
    candidates = []
    for rel in findings.get("doc_files", []):
        path = target / rel
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        headings = [line for line in lines if line.startswith("#")]
        if headings:
            candidates.append({"path": rel, "headings": len(headings)})
    return candidates


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "imported-doc"


def htext(value) -> str:
    return html.escape(str(value), quote=False)


def hattr(value) -> str:
    return html.escape(str(value), quote=True)


def checked_page_name(context_dir: Path, name: str) -> str:
    return resolve_context_page(context_dir, name).relative_to(context_dir).as_posix()


def absorb_docs(target: Path, context_dir: Path, findings: dict, today: str) -> list:
    imported = []
    for candidate in doc_import_candidates(target, findings):
        source = target / candidate["path"]
        text = source.read_text(errors="replace")
        title = next((line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")), source.stem)
        digest = hashlib.sha1(candidate["path"].encode("utf-8")).hexdigest()[:8]
        name = checked_page_name(context_dir, f"doc-{slugify(title)}-{digest}.html")
        title_text = htext(title)
        title_attr = hattr(title)
        source_text = htext(candidate["path"])
        source_attr = hattr(candidate["path"])
        body = "\n".join(f"      <p>{htext(line)}</p>" for line in text.splitlines() if line and not line.startswith("#"))
        page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="{title_attr}">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="read-when" content="Need imported notes from {source_attr}">
  <meta name="update-when" content="{source_attr} changes or imported notes are reviewed">
  <meta name="tracks" content="{source_attr}">
</head>
<body>
  <header>
    <h1>{title_text}</h1>
    <p class="summary">Imported from {source_text}.</p>
  </header>
  <main>
    <section id="overview">
      <h2>Overview</h2>
{body}
    </section>
  </main>
  <footer>
    <nav class="see-also">
      <a href="./index.html">Index</a>
    </nav>
  </footer>
</body>
</html>
"""
        write_atomic(context_dir / name, page_html, context_root=context_dir)
        archive = context_dir / "archived" / candidate["path"]
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, archive)
        imported.append({"source": candidate["path"], "page": name, "archive": str(archive.relative_to(context_dir))})
    if imported:
        index_path = context_dir / "index.html"
        links = "\n".join(
            f'      <li><a href="./{hattr(item["page"])}">{htext(item["page"])}</a> — imported from {htext(item["source"])}</li>'
            for item in imported
        )
        index = index_path.read_text(errors="replace").replace("      </ul>", links + "\n      </ul>", 1)
        write_atomic(index_path, index, context_root=context_dir)
    return imported


def generate_skeleton(target: Path, pages: list, config: dict = None):
    """Generate the full context/ directory structure."""
    context_dir = target / "context"
    context_dir.mkdir(exist_ok=True)
    (context_dir / "docs").mkdir(exist_ok=True)
    (context_dir / "scripts").mkdir(exist_ok=True)
    (context_dir / "hooks").mkdir(exist_ok=True)
    (context_dir / "archived").mkdir(exist_ok=True)

    # Copy scripts from skill
    scripts_src = SKILL_ROOT / "scripts"
    scripts_dst = context_dir / "scripts"
    for script in list(scripts_src.glob("*.py")) + list(scripts_src.glob("*.sh")):
        if script.name != "bootstrap.py":  # Don't copy bootstrap into project
            shutil.copy2(script, scripts_dst / script.name)
    runtime_policy = TEMPLATES_DIR / "runtime-policy.md"
    if runtime_policy.exists():
        shutil.copy2(runtime_policy, context_dir / "runtime-policy.md")
    hooks_src = SKILL_ROOT / "hooks"
    hooks_dst = context_dir / "hooks"
    if hooks_src.exists():
        for hook in hooks_src.glob("*.sh"):
            shutil.copy2(hook, hooks_dst / hook.name)

    # Generate config.json
    config_data = config or {
        "projectName": target.name,
        "maxLinesPerPage": 200,
        "repoRoots": [{"path": ".", "label": "main"}],
        "staleLockMinutes": 30,
        "ledgerRenderLimit": 75,
        "autoGenerateDocs": True,
        "ignoreTracks": ["build/**", "dist/**", "vendor/**", "node_modules/**"],
    }
    permission_defaults = load_permission_defaults()
    for key in ("defaultRole", "agentRoles", "permissionProfiles"):
        if key in permission_defaults:
            config_data.setdefault(key, permission_defaults[key])
    write_atomic(context_dir / "config.json", json.dumps(config_data, indent=2) + "\n", context_root=context_dir)

    # Generate index.html
    today = today_utc()
    project_name = config_data.get('projectName', target.name)
    project_text = htext(project_name)
    project_attr = hattr(project_name)
    page_links = []
    for page in pages:
        if page["name"] == "index.html":
            continue
        page_name = checked_page_name(context_dir, page["name"])
        page_links.append(f'      <li><a href="./{hattr(page_name)}">{htext(page_name)}</a> — {htext(page["purpose"])}</li>')

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="{project_attr} Context">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="read-when" content="Starting any task in this project">
  <meta name="tracks" content="context-only">
</head>
<body>
  <header>
    <h1>{project_text} — Context Map</h1>
    <p class="summary">Entry point for all project knowledge. Start here.</p>
  </header>

  <main>
    <section id="pages">
      <h2>Pages</h2>
      <ul>
{chr(10).join(page_links)}
      </ul>
    </section>

    <section id="rules">
      <h2>Rules</h2>
      <ul>
        <li>Max 200 lines per page (including HTML boilerplate)</li>
        <li>One topic per page — split if two concerns emerge</li>
        <li>Self-contained: removing any link must not break comprehension</li>
        <li>Always acquire lock before editing (see <a href="./ledger.html">ledger</a>)</li>
        <li>Run <code>python context/scripts/validate.py</code> after edits</li>
        <li>Run <code>python context/scripts/close-task.py</code> when done</li>
      </ul>
    </section>
  </main>

  <footer>
    <nav class="see-also">
      <a href="./ledger.html">Lock Ledger</a>
      <a href="./agent-tree.html">Agent Tree</a>
      <a href="./decisions.html">Decisions</a>
    </nav>
  </footer>
</body>
</html>
"""
    write_atomic(context_dir / "index.html", index_html, context_root=context_dir)

    # Generate control-plane.html
    control_plane_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="Control Plane">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="read-when" content="Before choosing task class or escalation path">
  <meta name="update-when" content="Task workflow, permissions, or validation policy changes">
  <meta name="tracks" content="context-only">
</head>
<body>
  <header>
    <h1>Control Plane</h1>
    <p class="summary">Runtime checklist for script-owned context workflow.</p>
  </header>

  <main>
    <section id="task-classes">
      <h2>Task Classes</h2>
      <ul>
        <li>Read-only: no locks.</li>
        <li>Tiny write: acquire page lock, edit narrowly, close task.</li>
        <li>Standard write: route files, acquire lock, validate, close task.</li>
      </ul>
    </section>

    <section id="escalation">
      <h2>Escalation</h2>
      <p>Use orchestrator resolution for blocked locks, stale tracks, unmatched files, and orphan context pages.</p>
    </section>
  </main>

  <footer>
    <nav class="see-also">
      <a href="./index.html">Index</a>
      <a href="./ledger.html">Lock Ledger</a>
    </nav>
  </footer>
</body>
</html>
"""
    write_atomic(context_dir / "control-plane.html", control_plane_html, context_root=context_dir)

    # Generate ledger event log and rendered view.
    write_atomic(context_dir / "ledger-events.ndjson", "", context_root=context_dir)
    ledger_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="Lock Ledger">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="read-when" content="Before editing any context page">
  <meta name="update-when" content="Lock acquired or released">
  <meta name="tracks" content="context-only">
</head>
<body>
  <header>
    <h1>Lock Ledger</h1>
    <p class="summary">Active locks and rendered event history from ledger-events.ndjson.</p>
  </header>

  <main>
    <section id="active-locks">
      <h2>Active Locks</h2>
      <table>
        <thead>
          <tr><th>Page</th><th>Agent</th><th>Acquired (UTC)</th><th>Purpose</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

    <section id="protocol">
      <h2>Protocol</h2>
      <ol>
        <li>Run <code>python context/scripts/start-task.py --page X --intent "Y"</code></li>
        <li>If lock acquired: proceed with edit</li>
        <li>If contention: request orchestrator arbitration</li>
        <li>When done: <code>python context/scripts/close-task.py --page X --summary "Y"</code></li>
      </ol>
      <p>Locks stale after {config_data.get('staleLockMinutes', 30)} minutes. Any agent may break stale locks.</p>
    </section>

    <section id="events">
      <h2>Events</h2>
      <p>Generated from <code>ledger-events.ndjson</code>.</p>
      <table>
        <thead>
          <tr><th>Time</th><th>Event</th><th>Page</th><th>Agent</th><th>Status</th><th>Details</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>
  </main>

  <footer>
    <nav class="see-also">
      <a href="./index.html">Index</a>
    </nav>
  </footer>
</body>
</html>
"""
    write_atomic(context_dir / "ledger.html", ledger_html, context_root=context_dir)

    # Generate agent-tree.html
    agent_tree_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="Agent Tree">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="read-when" content="Before escalating lock release or coordination questions">
  <meta name="update-when" content="Agent spawned, blocked, handed off, or closed">
  <meta name="tracks" content="context-only">
</head>
<body>
  <header>
    <h1>Agent Tree</h1>
    <p class="summary">Advisory view of active agent work. Lock authority remains page metas and ledger active locks.</p>
  </header>

  <main>
    <section id="tree">
      <h2>Tree</h2>
      <ul class="agent-tree">
      </ul>
    </section>

    <section id="agent-rows">
      <h2>Agent Records</h2>
      <table>
        <thead>
          <tr><th>Time</th><th>Agent</th><th>Parent</th><th>Role</th><th>Task</th><th>Page</th><th>Status</th><th>Details</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>
  </main>

  <footer>
    <nav class="see-also">
      <a href="./index.html">Index</a>
      <a href="./ledger.html">Lock Ledger</a>
    </nav>
  </footer>
</body>
</html>
"""
    write_atomic(context_dir / "agent-tree.html", agent_tree_html, context_root=context_dir)

    # Generate decisions.html
    decisions_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="Decision Graph">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="read-when" content="Before making architectural choices">
  <meta name="update-when" content="New decision made or existing one revised">
  <meta name="tracks" content="context-only">
</head>
<body>
  <header>
    <h1>Decision Graph</h1>
    <p class="summary">Architectural decisions, their rationale, and implementation refs.</p>
  </header>

  <main>
    <section id="decisions">
      <h2>Decisions</h2>

      <article class="decision" id="dec-001" data-status="accepted" data-tracks="context-only">
        <h3>DEC-001: Context Architecture <time>{today}</time></h3>
        <dl>
          <dt>Question</dt><dd>How should this project store durable agent context?</dd>
          <dt>Decision</dt><dd>HTML source of truth with auto-generated markdown. Script-driven lock/ledger/validation.</dd>
          <dt>Rationale</dt><dd>HTML gives semantic parsing without regex. Scripts make ritual deterministic. Markdown serves humans.</dd>
          <dt>Consequences</dt><dd>Scripts own validation and routing. Agents own judgment about durable meaning.</dd>
          <dt>Review when</dt><dd>HTML pages stop fitting the project workflow or generated markdown becomes the source of truth.</dd>
          <dt>Implemented in</dt>
          <dd><code>context/scripts/</code> — all automation</dd>
        </dl>
      </article>
    </section>
  </main>

  <footer>
    <nav class="see-also">
      <a href="./index.html">Index</a>
    </nav>
  </footer>
</body>
</html>
"""
    write_atomic(context_dir / "decisions.html", decisions_html, context_root=context_dir)

    # Generate stub pages for each suggested domain page
    for page in pages:
        if page["name"] in ("index.html", "control-plane.html", "ledger.html", "agent-tree.html", "decisions.html"):
            continue
        if page.get("auto"):
            continue

        page_name = checked_page_name(context_dir, page["name"])
        purpose_text = htext(page["purpose"])
        purpose_attr = hattr(page["purpose"])
        purpose_lower_text = htext(page["purpose"].lower())
        purpose_lower_attr = hattr(page["purpose"].lower())
        stub_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="{purpose_attr}">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="read-when" content="Need {purpose_lower_attr}">
  <meta name="update-when" content="{purpose_attr} changes">
  <meta name="tracks" content="context-only">
</head>
<body>
  <header>
    <h1>{purpose_text}</h1>
    <p class="summary">TODO: Fill in from source analysis.</p>
  </header>

  <main>
    <section id="overview">
      <h2>Overview</h2>
      <p>This page documents: {purpose_lower_text}.</p>
    </section>
  </main>

  <footer>
    <nav class="see-also">
      <a href="./index.html">Index</a>
    </nav>
  </footer>
</body>
</html>
"""
        page_path = context_dir / page_name
        if not page_path.exists():
            write_atomic(page_path, stub_html, context_root=context_dir)

    return context_dir


def main():
    parser = argparse.ArgumentParser(description="Bootstrap context/ architecture")
    parser.add_argument("--target", required=True, help="Project root directory")
    parser.add_argument("--scan", action="store_true", help="Scan only, print findings")
    parser.add_argument("--generate", action="store_true", help="Generate from config")
    parser.add_argument("--config", help="Path to config JSON with page list")
    parser.add_argument("--pages-json", help="JSON string of pages to generate")
    parser.add_argument("--absorb-docs", action="store_true", help="Import headed docs into context pages and archive copies")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"ERROR: {target} is not a directory")
        sys.exit(1)

    # Scan
    findings = scan_repo(target)

    if args.scan:
        # Print findings for LLM consumption
        print(json.dumps(findings, indent=2))
        print("\n--- SUGGESTED PAGES ---")
        pages = generate_suggested_pages(findings)
        print(json.dumps(pages, indent=2))
        print("\n--- DOC IMPORT CANDIDATES ---")
        print(json.dumps(doc_import_candidates(target, findings), indent=2))
        return

    # Load config if provided
    config = None
    pages = None
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            data = json.loads(config_path.read_text())
            config = data.get("config", data)
            pages = data.get("pages")

    if args.pages_json:
        pages = json.loads(args.pages_json)

    if not pages:
        pages = generate_suggested_pages(findings)

    # Generate
    try:
        context_dir = generate_skeleton(target, pages, config)
        imported = absorb_docs(target, context_dir, findings, today_utc()) if args.absorb_docs else []
    except ValueError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)
    print(f"Generated context/ at {context_dir}")
    print(f"  - {len(list(context_dir.glob('*.html')))} HTML pages")
    print(f"  - {len(list((context_dir / 'scripts').glob('*.py')))} scripts")
    print(f"  - {len(list((context_dir / 'hooks').glob('*.sh')))} hooks")
    print(f"  - config.json")
    print(f"  - runtime-policy.md")
    if findings.get("doc_files"):
        print(f"  - doc import candidates: {len(doc_import_candidates(target, findings))} (use --absorb-docs to import)")
    if imported:
        print(f"  - imported docs: {len(imported)}")
    print(f"\nNext steps:")
    print(f"  1. Review and fill stub pages with project-specific content")
    print(f"  2. Run: python context/scripts/validate.py")
    print(f"  3. Add to CLAUDE.md: see context/index.html for knowledge base")
    print(f"  4. For real ledger hardening, have root/elevated/non-agent user run: context/scripts/harden-ledger.sh context")


if __name__ == "__main__":
    main()
