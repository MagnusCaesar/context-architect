#!/usr/bin/env python3
"""capture-candidates.py — append a captured candidate to capture-inbox.html.

Level-2 capture: writes ONLY to the inbox, never to the live decisions/
failure-todos/open-questions graph. Dedupes against existing pending entries.
"""
import argparse, html, re, sys
from pathlib import Path

from context_utils import firstmate_root

KINDS = {"decision", "failure", "open-question"}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()

def existing_pending_summaries(content: str):
    out = []
    for m in re.finditer(r'<article class="candidate"[^>]*data-status="pending"[^>]*>(.*?)</article>',
                         content, re.S):
        sm = re.search(r'data-summary="([^"]*)"', m.group(0))
        if sm:
            out.append(_norm(html.unescape(sm.group(1))))  # unescape so stored &quot; matches raw "
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default=str(firstmate_root() / "context" / "capture-inbox.html"))
    ap.add_argument("--summary", required=True)
    ap.add_argument("--kind", required=True, choices=sorted(KINDS))
    ap.add_argument("--source", default="")
    args = ap.parse_args()

    inbox = Path(args.inbox)
    if not inbox.exists():
        print(f"inbox not found: {inbox}", file=sys.stderr)
        sys.exit(1)

    content = inbox.read_text()
    if _norm(args.summary) in existing_pending_summaries(content):
        print("duplicate pending candidate; skipped", file=sys.stderr)
        return  # idempotent no-op

    safe_summary = html.escape(args.summary, quote=True)
    safe_source = html.escape(args.source, quote=True)
    article = (
        f'<article class="candidate" data-kind="{args.kind}" '
        f'data-status="pending" data-summary="{safe_summary}" data-source="{safe_source}">'
        f'{args.kind}: {html.escape(args.summary)} (source: {html.escape(args.source)}, status=pending)'  # body text (display only)
        f'</article>\n'
    )
    if '</section>' in content:
        content = content.replace('</section>', article + '</section>', 1)
    else:
        content = content.replace('</body>', article + '</body>', 1)
    inbox.write_text(content)

if __name__ == "__main__":
    main()
