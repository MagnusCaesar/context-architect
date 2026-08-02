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
from platforms import PlatformError, install_bootloaders, platform_choice, platform_homes, resolve_platform


SKILL_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"

CORE_PAGES = [
    {"name": "index.html", "purpose": "Root entry point and page map", "auto": True},
    {"name": "control-plane.html", "purpose": "Runtime workflow checklist", "auto": True},
    {"name": "ledger.html", "purpose": "Concurrency locks, source claims, and history", "auto": True},
    {"name": "agent-tree.html", "purpose": "Advisory agent coordination tree", "auto": True},
    {"name": "decisions.html", "purpose": "Decision graph and rationale", "auto": True},
    {"name": "failure-todos.html", "purpose": "Scoped unresolved failures and repair routing", "auto": True},
    {"name": "open-questions.html", "purpose": "Unresolved assumptions and blocking questions", "auto": True},
    {"name": "reproducibility.html", "purpose": "Setup, tools, environment, and artifact paths", "auto": True},
    {"name": "run-intent.html", "purpose": "Router from intent to runbooks and expected outcomes", "auto": True},
    {"name": "recognized-commits.html", "purpose": "Recognized git ranges and context sync state", "auto": True},
]

CORE_PAGE_NAMES = {page["name"] for page in CORE_PAGES}
INDEX_ONLY_PAGES = [
    {"name": "decisions/archive.html", "purpose": "Archived decision node index"},
    {"name": "failure-todos/archive.html", "purpose": "Archived failure todo node index"},
    {"name": "open-questions/archive.html", "purpose": "Archived open question node index"},
]
BLOCKED_GENERATED_PAGES = {"rules.html", "source-claims.html"}


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
    pages = [dict(page) for page in CORE_PAGES]

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


def write_simple_page(context_dir: Path, name: str, title: str, summary: str, body: str, today: str, see_also=None) -> None:
    links = see_also or [("Index", "./index.html")]
    nav = "\n".join(f'      <a href="{hattr(href)}">{htext(label)}</a>' for label, href in links)
    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="title" content="{hattr(title)}">
  <meta name="created" content="{today}">
  <meta name="updated" content="{today}">
  <meta name="locked" content="false">
  <meta name="locked-by" content="">
  <meta name="locked-at" content="">
  <meta name="read-when" content="Need {hattr(title)} context">
  <meta name="update-when" content="{hattr(title)} changes">
  <meta name="tracks" content="context-only">
</head>
<body>
  <header>
    <h1>{htext(title)}</h1>
    <p class="summary">{htext(summary)}</p>
  </header>

  <main>
{body}
  </main>

  <footer>
    <nav class="see-also">
{nav}
    </nav>
  </footer>
</body>
</html>
"""
    write_atomic(context_dir / name, page_html, context_root=context_dir)


def checked_page_name(context_dir: Path, name: str) -> str:
    return resolve_context_page(context_dir, name).relative_to(context_dir).as_posix()


def normalize_pages(pages):
    """Ensure V1 structural pages exist and excluded pages are never generated."""
    normalized = [dict(page) for page in CORE_PAGES]
    seen = {page["name"] for page in normalized}
    for page in pages or []:
        name = page.get("name")
        if not name or name in seen or name in BLOCKED_GENERATED_PAGES:
            continue
        normalized.append(page)
        seen.add(name)
    return normalized


CLAUDE_HOOKS_SETTINGS = {
    "hooks": {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "bash context/hooks/remind-capture-decision.sh",
                    }
                ],
            }
        ],
        "PreToolUse": [
            {
                "matcher": "Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": "bash context/hooks/pre-edit-context-inject.sh",
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Edit|Write",
                "hooks": [
                    {
                        "type": "command",
                        "command": "bash context/hooks/post-edit-validate-and-stale.sh",
                    }
                ],
            }
        ],
    }
}

_STOP_HOOK = {
    "Stop": [
        {"hooks": [
            {"type": "command", "command": "bash context/hooks/capture-on-stop.sh"},
            {"type": "command", "command": "bash context/hooks/auto-commit-context.sh"},
        ]}
    ]
}
# Commit context when a SUBAGENT finishes editing too (subagents do most edits;
# whoever held the lock commits when they finish, which releases the lock).
_SUBAGENT_STOP_HOOK = {
    "SubagentStop": [
        {"hooks": [
            {"type": "command", "command": "bash context/hooks/auto-commit-context.sh"},
        ]}
    ]
}
_SESSION_START_HOOK = {
    "SessionStart": [
        {"hooks": [{"type": "command",
                    "command": "bash context/hooks/session-start-inject.sh"}]}
    ]
}
_SUBAGENT_START_HOOK = {
    "SubagentStart": [
        {"hooks": [{"type": "command",
                    "command": "bash context/hooks/subagent-start-inject.sh"}]}
    ]
}
_READ_DIRECTION_UPS = {"type": "command",
                       "command": "bash context/hooks/remind-context-read.sh"}
_READ_DIRECTION_POST = {
    "matcher": "Read",
    "hooks": [{"type": "command",
               "command": "bash context/hooks/post-read-context-gate.sh"}]
}

def hooks_for_scope(scope: str) -> dict:
    """Return the hooks dict to register for the given scope."""
    hooks = json.loads(json.dumps(CLAUDE_HOOKS_SETTINGS["hooks"]))  # deep copy
    hooks.update(_STOP_HOOK)                 # both scopes capture + commit on Stop
    hooks.update(_SUBAGENT_STOP_HOOK)        # commit when a subagent finishes editing
    hooks.update(_SUBAGENT_START_HOOK)       # both scopes inject into subagents
    # read-direction: append remind-context-read to UserPromptSubmit, add Read gate
    hooks["UserPromptSubmit"][0]["hooks"].append(dict(_READ_DIRECTION_UPS))
    hooks.setdefault("PostToolUse", []).append(dict(_READ_DIRECTION_POST))
    if scope == "global":
        hooks.update(_SESSION_START_HOOK)    # global also injects at session start
    # Final deep copy so the returned dict shares no nested objects with the
    # module-level fragments spliced in above (the contract is "independent dict").
    return json.loads(json.dumps(hooks))


def absolutize_hooks(hooks: dict, target: Path) -> dict:
    """Rewrite 'bash context/hooks/X' commands to absolute paths.

    Hooks fire with the session's cwd, which is not always the project root, so
    relative 'context/hooks/...' fails from any subdir. Anchor them to target.
    """
    prefix = "bash context/hooks/"
    abs_base = f"bash {target.resolve()}/context/hooks/"
    for groups in hooks.values():
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "")
                if cmd.startswith(prefix):
                    h["command"] = abs_base + cmd[len(prefix):]
    return hooks


def install_git_hook(repo_dir: Path, hooks_src: Path, name: str) -> bool:
    """Install a named git hook into repo_dir's real hooks dir.

    Asks git for the hooks path so it works whether context/ is its own repo
    (project layout) or a subdir of the repo (firstmate-home layout). Returns
    True if installed.
    """
    src = hooks_src / name
    if not src.exists():
        return False
    try:
        # --absolute-git-dir is unambiguous across layouts (no cwd-relative paths).
        r = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            capture_output=True, text=True, cwd=str(repo_dir), timeout=5,
        )
        if r.returncode != 0:
            return False
        hp = Path(r.stdout.strip()) / "hooks"
    except (subprocess.TimeoutExpired, OSError):
        return False
    hp.mkdir(parents=True, exist_ok=True)
    dst = hp / name
    shutil.copy2(src, dst)
    dst.chmod(0o755)
    return True


def install_post_commit(context_dir: Path, hooks_src: Path) -> bool:
    """Install the post-commit hook into the context repo's hooks dir."""
    return install_git_hook(context_dir, hooks_src, "post-commit")


def install_pre_commit(context_dir: Path, hooks_src: Path, config: dict | None) -> list[str]:
    """Install the pre-commit hook (secret-scan + context validate).

    Installs into the context repo AND each repoRoots[].path (resolved against
    the project root, i.e. context_dir.parent). The hook itself detects at
    runtime whether it is running in the context repo or a plain code repo.
    Returns the list of repo dirs where it was installed (deduped by git dir).
    """
    installed = []
    seen_gitdirs = set()
    project_root = context_dir.parent
    roots = [context_dir]
    if config:
        for rr in config.get("repoRoots", []):
            p = rr.get("path") if isinstance(rr, dict) else None
            if p:
                roots.append((project_root / p).resolve())
    for repo_dir in roots:
        try:
            gd = subprocess.run(
                ["git", "rev-parse", "--absolute-git-dir"],
                capture_output=True, text=True, cwd=str(repo_dir), timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if gd.returncode != 0:
            continue
        key = gd.stdout.strip()
        if key in seen_gitdirs:
            continue
        seen_gitdirs.add(key)
        if install_git_hook(repo_dir, hooks_src, "pre-commit"):
            installed.append(str(repo_dir))
    return installed


def install_platform_hooks(target: Path, platforms, scope: str = "project") -> None:
    """Install legacy hooks for explicitly selected platforms.

    Claude Code: auto-creates .claude/settings.json with stdin-based wrapper hooks.
    Codex: hooks are copied to context/hooks/ but not auto-installed (Codex agents
    read the install comment in each hook script and AGENTS.md bootloader instructions).
    """
    if "claude" not in platforms:
        return
    claude_dir = target / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_path = claude_dir / "settings.json"
    new_hooks = absolutize_hooks(hooks_for_scope(scope), target)
    if settings_path.exists():
        existing = json.loads(settings_path.read_text(errors="replace"))
        if "hooks" in existing:
            return  # idempotent guard preserved
        existing["hooks"] = new_hooks
        write_atomic(settings_path, json.dumps(existing, indent=2) + "\n")
    else:
        write_atomic(settings_path, json.dumps({"hooks": new_hooks}, indent=2) + "\n")


SELF_HEALING_CONFIG_DEFAULTS = {
    "staleLockMinutes": 30,
    "autoAcquireOnEdit": True,
    "autoReleaseOnCommit": True,
    "autoReleaseIdleMinutes": 1440,
    "contentionBreakMinutes": 3,
    "lockMutexTimeoutSec": 10,
    "scope": "project",
    "autoCommitContext": True,
}


def refresh_context(target: Path, platforms) -> dict:
    """Idempotently refresh skill-owned machinery in an existing context/ dir.

    Updates scripts, hooks, git post-commit, .gitignore, settings.json hooks, and
    adds any missing self-healing config keys. Never touches authored content
    (index.html, decisions/, failure-todos/, open-questions/, ledger) or existing
    config values. Runs validate.py and returns a structured report.
    """
    context_dir = target / "context"
    if not (context_dir / "index.html").exists():
        return {"status": "error", "error": f"{context_dir}/index.html not found — not a context-arch dir; run full bootstrap first"}

    updated = []

    # Ensure machinery dirs exist (idempotent)
    for d in ("scripts", "hooks", ".locks", "archived", "runbooks"):
        (context_dir / d).mkdir(exist_ok=True)
    for node_dir in ("decisions", "failure-todos", "open-questions"):
        (context_dir / node_dir).mkdir(exist_ok=True)
        (context_dir / node_dir / "archived").mkdir(exist_ok=True)

    # Copy skill scripts (overwrite — these are skill-owned, not authored)
    scripts_src = SKILL_ROOT / "scripts"
    scripts_dst = context_dir / "scripts"
    for script in list(scripts_src.glob("*.py")) + list(scripts_src.glob("*.sh")):
        if script.name != "bootstrap.py":
            shutil.copy2(script, scripts_dst / script.name)
            updated.append(f"scripts/{script.name}")

    runtime_policy = TEMPLATES_DIR / "runtime-policy.md"
    if runtime_policy.exists():
        shutil.copy2(runtime_policy, context_dir / "runtime-policy.md")
        updated.append("runtime-policy.md")

    # Copy skill hooks (overwrite)
    hooks_src = SKILL_ROOT / "hooks"
    hooks_dst = context_dir / "hooks"
    if hooks_src.exists():
        for hook in hooks_src.glob("*.sh"):
            shutil.copy2(hook, hooks_dst / hook.name)
            updated.append(f"hooks/{hook.name}")

    # Install/refresh git post-commit hook
    if install_post_commit(context_dir, hooks_src):
        updated.append("git post-commit hook")

    # Install/refresh git pre-commit hook (secret-scan + validate) into
    # the context repo and every repoRoots[].path.
    _pc_cfg = None
    _pc_cfg_path = context_dir / "config.json"
    if _pc_cfg_path.exists():
        try:
            _pc_cfg = json.loads(_pc_cfg_path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            pass
    if install_pre_commit(context_dir, hooks_src, _pc_cfg):
        updated.append("git pre-commit hook")

    # Ensure .gitignore has .locks/
    ctx_gitignore = context_dir / ".gitignore"
    if not ctx_gitignore.exists():
        write_atomic(ctx_gitignore, ".locks/\nledger-archive/\n", context_root=context_dir)
        updated.append(".gitignore")
    else:
        gi_content = ctx_gitignore.read_text()
        if ".locks/" not in gi_content:
            write_atomic(ctx_gitignore, gi_content.rstrip() + "\n.locks/\n", context_root=context_dir)
            updated.append(".gitignore")

    # Merge missing self-healing config keys (preserve existing values)
    config_path = context_dir / "config.json"
    config_added = []
    if config_path.exists():
        cfg = json.loads(config_path.read_text(errors="replace"))
        for k, v in SELF_HEALING_CONFIG_DEFAULTS.items():
            if k not in cfg:
                cfg[k] = v
                config_added.append(k)
        if config_added:
            write_atomic(config_path, json.dumps(cfg, indent=2) + "\n", context_root=context_dir)
            updated.append(f"config.json (+{','.join(config_added)})")

    # Force-update settings.json hooks (install_platform_hooks refuses if hooks exist)
    if "claude" in platforms:
        claude_dir = target / ".claude"
        claude_dir.mkdir(exist_ok=True)
        settings_path = claude_dir / "settings.json"
        if settings_path.exists():
            existing = json.loads(settings_path.read_text(errors="replace"))
        else:
            existing = {}
        # Read stored scope so refresh preserves global hooks (SessionStart+Stop)
        _cfg_path = context_dir / "config.json"
        _scope = "project"
        if _cfg_path.exists():
            try:
                _scope = json.loads(_cfg_path.read_text(errors="replace")).get("scope", "project")
            except (json.JSONDecodeError, OSError):
                pass
        existing["hooks"] = absolutize_hooks(hooks_for_scope(_scope), context_dir.parent)
        write_atomic(settings_path, json.dumps(existing, indent=2) + "\n")
        updated.append(".claude/settings.json (hooks)")

    # Re-render managed bootloader block (marker-delimited; authored prose untouched)
    for _bl in install_bootloaders(target, platforms):
        updated.append(_bl)

    # Run validation, capture failures
    validate_script = scripts_dst / "validate.py"
    validate_failures = []
    validate_ran = False
    if validate_script.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(validate_script)],
                capture_output=True, text=True, cwd=str(target), timeout=60,
            )
            validate_ran = True
            validate_passed = result.returncode == 0
            for line in result.stdout.splitlines():
                if line.startswith("FAIL:") or line.strip().startswith("- "):
                    validate_failures.append(line.strip())
        except (subprocess.TimeoutExpired, OSError) as e:
            validate_passed = False
            validate_failures.append(f"validate.py error: {e}")
    else:
        validate_passed = None

    return {
        "status": "refreshed",
        "target": str(target),
        "updated": updated,
        "config_keys_added": config_added,
        "validate_ran": validate_ran,
        "validate_passed": validate_passed,
        "validate_failures": validate_failures,
    }


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


def generate_skeleton(target: Path, pages: list, config: dict = None, scope: str = "project", platforms=("claude",)):
    """Generate the full context/ directory structure."""
    pages = normalize_pages(pages)
    context_dir = target / "context"
    context_dir.mkdir(exist_ok=True)
    (context_dir / "scripts").mkdir(exist_ok=True)
    (context_dir / "hooks").mkdir(exist_ok=True)
    (context_dir / "archived").mkdir(exist_ok=True)
    (context_dir / "runbooks").mkdir(exist_ok=True)
    (context_dir / ".locks").mkdir(exist_ok=True)
    (target / "docs" / "context").mkdir(parents=True, exist_ok=True)
    for node_dir in ("decisions", "failure-todos", "open-questions"):
        (context_dir / node_dir).mkdir(exist_ok=True)
        (context_dir / node_dir / "archived").mkdir(exist_ok=True)

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

    # Install git post-commit hook for auto-release
    install_post_commit(context_dir, hooks_src)

    # Install git pre-commit hook (secret-scan + validate) into the context
    # repo and every repoRoots[].path.
    install_pre_commit(context_dir, hooks_src, config)

    # Create .gitignore for .locks/ (ephemeral sentinels)
    ctx_gitignore = context_dir / ".gitignore"
    if not ctx_gitignore.exists():
        write_atomic(ctx_gitignore, ".locks/\nledger-archive/\n", context_root=context_dir)
    else:
        gi_content = ctx_gitignore.read_text()
        if ".locks/" not in gi_content:
            write_atomic(ctx_gitignore, gi_content.rstrip() + "\n.locks/\n", context_root=context_dir)

    # Generate config.json
    config_data = config or {
        "projectName": target.name,
        "maxLinesPerPage": 200,
        "repoRoots": [{"path": ".", "label": "main"}],
        "staleLockMinutes": 30,
        "autoAcquireOnEdit": True,
        "autoReleaseOnCommit": True,
        "autoReleaseIdleMinutes": 1440,
        "contentionBreakMinutes": 3,
        "lockMutexTimeoutSec": 10,
        "ledgerRenderLimit": 75,
        "autoGenerateDocs": True,
        "ignoreTracks": ["build/**", "dist/**", "vendor/**", "node_modules/**"],
        "scope": scope,
        "autoCommitContext": True,
    }
    # If a config was passed in explicitly, still stamp bootstrap selections on it:
    config_data.setdefault("scope", scope)
    config_data["platform"] = platform_choice(platforms)
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
    for page in INDEX_ONLY_PAGES:
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
  <meta name="update-when" content="Pages are added, removed, or reorganized">
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

    <section id="projection">
      <h2>Human Projection</h2>
      <ul>
        <li><a href="../docs/context/">docs/context/</a> — generated human-facing context docs</li>
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
      <a href="./failure-todos.html">Failure Todos</a>
      <a href="./open-questions.html">Open Questions</a>
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

    <section id="routers">
      <h2>Routers</h2>
      <ul>
        <li><a href="./failure-todos.html">Failure todos</a> block completion only when task scope intersects <code>affects</code>.</li>
        <li><a href="./open-questions.html">Open questions</a> block only when marked blocking for related scope.</li>
        <li><a href="./run-intent.html">Run intent</a> routes execution requests to runbooks; it does not execute commands.</li>
      </ul>
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

    <section id="active-source-claims">
      <h2>Active Source Claims</h2>
      <table>
        <thead>
          <tr><th>Claim</th><th>Agent</th><th>Paths</th><th>Mode</th><th>Started (UTC)</th></tr>
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
    <section id="routes">
      <h2>Routes</h2>
      <table>
        <thead>
          <tr><th>Area</th><th>Decision Nodes</th><th>Archive</th></tr>
        </thead>
        <tbody>
          <tr><td>Project</td><td><a href="./decisions/">decisions/</a></td><td><a href="./decisions/archive.html">archive</a></td></tr>
        </tbody>
      </table>
    </section>

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

    write_simple_page(
        context_dir,
        "decisions/archive.html",
        "Archived Decisions",
        "Index of decisions removed from routine routing.",
        """    <section id="archived-decisions">
      <h2>Archived Decision Nodes</h2>
      <table>
        <thead>
          <tr><th>Decision</th><th>Status</th><th>Archived (UTC)</th><th>Replacement</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>""",
        today,
        [("Decisions", "../decisions.html"), ("Index", "../index.html")],
    )

    write_simple_page(
        context_dir,
        "failure-todos.html",
        "Failure Todos",
        "Router for scoped unresolved failures and authorized repair work.",
        """    <section id="failure-routes">
      <h2>Failure Routes</h2>
      <table>
        <thead>
          <tr><th>Failure</th><th>Status</th><th>Affects</th><th>Node</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

    <section id="node-schema">
      <h2>Node Schema</h2>
      <p>Nodes live under <code>failure-todos/</code>. Status, affects, topics, repro, authorization, and resolution stay on the node.</p>
    </section>""",
        today,
        [("Index", "./index.html"), ("Archive", "./failure-todos/archive.html")],
    )

    write_simple_page(
        context_dir,
        "failure-todos/archive.html",
        "Archived Failure Todos",
        "Index of resolved, deprecated, or non-routine failure nodes.",
        """    <section id="archived-failures">
      <h2>Archived Failure Nodes</h2>
      <table>
        <thead>
          <tr><th>Failure</th><th>Final Status</th><th>Archived (UTC)</th><th>Resolution</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>""",
        today,
        [("Failure Todos", "../failure-todos.html"), ("Index", "../index.html")],
    )

    write_simple_page(
        context_dir,
        "open-questions.html",
        "Open Questions",
        "Router for unresolved assumptions, blocking questions, and answers.",
        """    <section id="question-routes">
      <h2>Question Routes</h2>
      <table>
        <thead>
          <tr><th>Question</th><th>Status</th><th>Blocking</th><th>Affects</th><th>Node</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

    <section id="node-schema">
      <h2>Node Schema</h2>
      <p>Nodes live under <code>open-questions/</code>. Blocking and affects fields decide related work impact.</p>
    </section>""",
        today,
        [("Index", "./index.html"), ("Archive", "./open-questions/archive.html")],
    )

    write_simple_page(
        context_dir,
        "open-questions/archive.html",
        "Archived Open Questions",
        "Index of answered or deferred question nodes.",
        """    <section id="archived-questions">
      <h2>Archived Question Nodes</h2>
      <table>
        <thead>
          <tr><th>Question</th><th>Final Status</th><th>Archived (UTC)</th><th>Answered By</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>""",
        today,
        [("Open Questions", "../open-questions.html"), ("Index", "../index.html")],
    )

    write_simple_page(
        context_dir,
        "reproducibility.html",
        "Reproducibility",
        "Project setup order, required tools, environment, and artifact paths.",
        """    <section id="setup">
      <h2>Setup</h2>
      <table>
        <thead>
          <tr><th>Order</th><th>Requirement</th><th>Command or Path</th><th>Notes</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

    <section id="do-not-assume">
      <h2>Do Not Assume</h2>
      <ul>
      </ul>
    </section>""",
        today,
    )

    write_simple_page(
        context_dir,
        "run-intent.html",
        "Run Intent Router",
        "Router only. Maps execution intent to runbooks and expected result categories.",
        """    <section id="intent-routes">
      <h2>Intent Routes</h2>
      <table>
        <thead>
          <tr><th>Intent</th><th>When To Use</th><th>Runbook</th><th>Expected Result</th><th>Affected Context</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

    <section id="runbooks">
      <h2>Runbooks</h2>
      <p>Command details live under <a href="./runbooks/">runbooks/</a>; this page only routes.</p>
    </section>""",
        today,
    )

    write_simple_page(
        context_dir,
        "recognized-commits.html",
        "Recognized Commits",
        "Router for git ranges that have been reflected into context.",
        """    <section id="recognized-ranges">
      <h2>Recognized Ranges</h2>
      <table>
        <thead>
          <tr><th>Range</th><th>Head</th><th>Recognized (UTC)</th><th>Ledger Event</th><th>Notes</th></tr>
        </thead>
        <tbody>
        </tbody>
      </table>
    </section>

    <section id="commit-refs">
      <h2>Commit References</h2>
      <p>Reference commits or ranges. Do not duplicate full git history here.</p>
    </section>""",
        today,
    )

    # Generate stub pages for each suggested domain page
    for page in pages:
        if page["name"] in CORE_PAGE_NAMES:
            continue
        if page["name"] in BLOCKED_GENERATED_PAGES:
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

    install_bootloaders(target, platforms)
    install_platform_hooks(target, platforms, scope=scope)
    return context_dir


def main():
    parser = argparse.ArgumentParser(description="Bootstrap context/ architecture")
    parser.add_argument("--target", required=True, help="Project root directory")
    parser.add_argument("--scan", action="store_true", help="Scan only, print findings")
    parser.add_argument("--generate", action="store_true", help="Generate from config")
    parser.add_argument("--config", help="Path to config JSON with page list")
    parser.add_argument("--pages-json", help="JSON string of pages to generate")
    parser.add_argument("--absorb-docs", action="store_true", help="Import headed docs into context pages and archive copies")
    parser.add_argument("--refresh", action="store_true", help="Idempotently refresh skill machinery in an existing context/ dir (preserves authored content + config values)")
    parser.add_argument("--platform", choices=["claude", "codex", "both"],
                        help="Target harness; required when detection is ambiguous")
    parser.add_argument("--scope", choices=["project", "global"], default="project",
                        help="project = standard per-project context (default); "
                             "global = first-mate cross-project context instance")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"ERROR: {target} is not a directory")
        sys.exit(1)

    # Refresh mode: update machinery only, never touch authored content
    if args.refresh:
        try:
            stored = json.loads((target / "context" / "config.json").read_text(errors="replace"))["platform"]
            platforms = resolve_platform(stored, {}, {})
        except (KeyError, OSError, json.JSONDecodeError, PlatformError) as e:
            print(json.dumps({"status": "error", "error": f"refresh requires stored platform: {e}"}))
            sys.exit(1)
        report = refresh_context(target, platforms)
        if report.get("status") == "error":
            print(json.dumps(report, indent=2))
            sys.exit(1)
        print(f"Refreshed context/ at {report['target']}")
        print(f"  - {len(report['updated'])} machinery files updated")
        if report.get("config_keys_added"):
            print(f"  - config keys added: {', '.join(report['config_keys_added'])}")
        if report.get("validate_ran"):
            if report["validate_passed"]:
                print("  - validation: PASS")
            else:
                print(f"  - validation: FAIL ({len(report['validate_failures'])} issues — pages may need migration to newer/stricter checks):")
                for f in report["validate_failures"]:
                    print(f"      {f}")
        print("  - new session required for managed instruction or hook changes to reload")
        return

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
        platforms = resolve_platform(args.platform, os.environ, platform_homes())
        context_dir = generate_skeleton(target, pages, config=config, scope=args.scope, platforms=platforms)
        imported = absorb_docs(target, context_dir, findings, today_utc()) if args.absorb_docs else []
    except ValueError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)
    print(f"Generated context/ at {context_dir}")
    print(f"  - {len(list(context_dir.rglob('*.html')))} HTML pages")
    print(f"  - {len(list((context_dir / 'scripts').glob('*.py')))} scripts")
    print(f"  - {len(list((context_dir / 'hooks').glob('*.sh')))} hooks")
    bootloader_files = []
    if "codex" in platforms:
        bootloader_files.append("AGENTS.md")
    if "claude" in platforms:
        bootloader_files.append("CLAUDE.md")
    print(f"  - {' and '.join(bootloader_files)} bootloader blocks")
    print(f"  - config.json")
    print(f"  - runtime-policy.md")
    print(f"  - context/runbooks/ and docs/context/")
    if findings.get("doc_files"):
        print(f"  - doc import candidates: {len(doc_import_candidates(target, findings))} (use --absorb-docs to import)")
    if imported:
        print(f"  - imported docs: {len(imported)}")
    print(f"\nNext steps:")
    print(f"  1. Review and fill stub pages with project-specific content")
    print(f"  2. Run: python3 context/scripts/validate.py")
    print(f"  3. For real ledger hardening, have root/elevated/non-agent user run: context/scripts/harden-ledger.sh context")
    print("  4. Start a new session for managed instructions and hooks to reload")


if __name__ == "__main__":
    main()
