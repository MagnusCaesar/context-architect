#!/usr/bin/env python3
"""seed-registry.py — find context-arch instances under roots, emit registry lines.

One line per project: name | abs-context-path | one-liner | active
"""
import argparse, os, re, sys
from pathlib import Path

def title_of(index_html: Path) -> str:
    try:
        m = re.search(r"<title>(.*?)</title>", index_html.read_text(errors="replace"), re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    except OSError:
        return ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--max-depth", type=int, default=4)
    args = ap.parse_args()

    seen = set()
    for root in args.roots:
        root = Path(root).resolve()
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            if depth > args.max_depth:
                dirnames[:] = []
                continue
            if Path(dirpath).name == "context" and "index.html" in filenames:
                ctx = Path(dirpath).resolve()
                if ctx in seen:
                    continue
                seen.add(ctx)
                name = ctx.parent.name
                print(f"{name} | {ctx} | {title_of(ctx / 'index.html')} | active")

if __name__ == "__main__":
    main()
