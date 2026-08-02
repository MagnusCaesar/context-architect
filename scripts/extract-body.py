#!/usr/bin/env python3
"""Print a context page's body as plain text — no <head> infra, no HTML tags.

Reads context HTML pages whose <head> is pure coordination metadata (locks,
tracks, read-when, reviewed-at) and whose <body> holds the actual knowledge.
Emits the title + readable body text so an agent can read a page for a fraction
of the tokens that `cat`-ing the raw HTML costs.

Usage: extract-body.py <page.html> [more.html ...]
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "tr", "section", "header",
         "footer", "div", "pre", "ul", "ol", "nav", "article", "blockquote"}
HEADING = {"h1", "h2", "h3", "h4"}


class BodyText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.skip = 0  # depth inside script/style
        self.out = []
        self._href = None

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
            return
        if not self.in_body:
            return
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "a":
            self._href = dict(attrs).get("href")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in HEADING:
            self.out.append("\n\n# ")
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
        elif tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag == "a" and self._href and self.in_body:
            self.out.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data):
        if self.in_body and not self.skip:
            self.out.append(data)


def extract(path: Path) -> str:
    raw = path.read_text(errors="replace")
    title = re.search(r'<meta\s+name="title"\s+content="([^"]*)"', raw)
    p = BodyText()
    p.feed(raw)
    text = "".join(p.out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    head = f"=== {title.group(1)} ({path.name}) ===" if title else f"=== {path.name} ==="
    return f"{head}\n{text}"


def demo():
    sample = (
        '<html><head><meta name="title" content="T">'
        '<meta name="locked" content="false"></head>'
        '<body><header><h1>Hi</h1><p class="summary">sum</p></header>'
        '<main><h2>Sec</h2><ul><li>one</li><li><a href="./x.html">two</a></li></ul>'
        '<script>junk()</script></main></body></html>'
    )
    import tempfile
    f = Path(tempfile.mktemp(suffix=".html"))
    f.write_text(sample)
    got = extract(f)
    f.unlink()
    assert "=== T" in got, got
    assert "junk" not in got, "script body leaked"
    assert "locked" not in got, "head infra leaked"
    assert "# Hi" in got and "# Sec" in got, got
    assert "- one" in got and "two (./x.html)" in got, got
    print("ok")


def main():
    args = sys.argv[1:]
    if args == ["--demo"]:
        demo()
        return
    if not args:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        sys.exit(1)
    print("\n\n".join(extract(Path(a)) for a in args))


if __name__ == "__main__":
    main()
