#!/usr/bin/env python3
"""seed-registry.py — find context-arch instances under roots, emit registry lines.

One line per project: name | abs-context-path | one-liner | active
"""
import argparse, html, os, re, sys
from pathlib import Path

from context_utils import write_atomic

START = "<!-- context-architecture:projects:start -->"
END = "<!-- context-architecture:projects:end -->"

def title_of(index_html: Path) -> str:
    try:
        m = re.search(r"<title>(.*?)</title>", index_html.read_text(errors="replace"), re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    except OSError:
        return ""


def discover(roots, max_depth=4):
    projects, seen = [], set()
    for root in roots:
        root = Path(root).resolve()
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            if depth > max_depth:
                dirnames[:] = []
                continue
            if Path(dirpath).name == "context" and "index.html" in filenames:
                ctx = Path(dirpath).resolve()
                if ctx in seen:
                    continue
                seen.add(ctx)
                projects.append((ctx.parent.name, str(ctx), title_of(ctx / "index.html"), "active"))
    return sorted(projects, key=lambda item: (item[0].lower(), item[1]))


def update_registry(registry: Path, projects) -> None:
    content = registry.read_text(errors="replace")
    if content.count(START) != 1 or content.count(END) != 1 or content.index(START) > content.index(END):
        raise ValueError("registry requires exactly one ordered managed project block")
    articles = "\n".join(
        f'<article class="project">{html.escape(str(name))} | {html.escape(str(path))} | '
        f'{html.escape(str(summary))} | {html.escape(str(status))}</article>'
        for name, path, summary, status in sorted(projects, key=lambda item: (str(item[0]).lower(), str(item[1])))
    )
    before, rest = content.split(START, 1)
    _, after = rest.split(END, 1)
    write_atomic(registry, before + START + ("\n" + articles if articles else "") + "\n" + END + after)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--registry", help="Update only the marker-delimited managed project block")
    args = ap.parse_args()
    projects = discover(args.roots, args.max_depth)
    if args.registry:
        update_registry(Path(args.registry), projects)
    else:
        for project in projects:
            print(" | ".join(project))

if __name__ == "__main__":
    main()
