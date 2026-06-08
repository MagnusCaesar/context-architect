#!/usr/bin/env python3
"""
Generate human-readable markdown docs from HTML source pages.

Strips metadata (lock state, timestamps, tags), converts HTML structure to
clean markdown, and writes to docs/context/.

Usage:
    python context/scripts/generate-docs.py
"""

import re
from html.parser import HTMLParser
from pathlib import Path


class HTMLToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__()
        self.output = []
        self.in_head = False
        self.in_footer = False
        self.current_tag = ""
        self.list_stack = []
        self.in_pre = False
        self.in_dt = False
        self.in_dd = False
        self.in_table = False
        self.table_rows = []
        self.current_row = []
        self.current_cell = ""
        self.in_header_tag = ""
        self.skip_content = False
        self.link_href = ""
        self.buffer = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "head":
            self.in_head = True
        elif tag == "footer":
            self.in_footer = True
        elif self.in_head or self.in_footer:
            return
        elif tag in ("h1", "h2", "h3"):
            prefix = "#" * int(tag[1])
            self.buffer = f"\n{prefix} "
        elif tag == "p" and not self.in_table:
            self.buffer = "\n"
        elif tag == "pre":
            self.in_pre = True
            self.buffer = "\n```\n"
        elif tag == "ul":
            self.list_stack.append("ul")
        elif tag == "ol":
            self.list_stack.append("ol")
        elif tag == "li":
            indent = "  " * (len(self.list_stack) - 1)
            if self.list_stack and self.list_stack[-1] == "ol":
                self.buffer = f"\n{indent}1. "
            else:
                self.buffer = f"\n{indent}- "
        elif tag == "dt":
            self.in_dt = True
            self.buffer += "\n**"
        elif tag == "dd":
            self.in_dd = True
            self.buffer += ": "
        elif tag == "code" and not self.in_pre:
            self.buffer = "`"
        elif tag == "strong":
            self.buffer = "**"
        elif tag == "a":
            href = attrs_dict.get("href", "")
            self.link_href = href.replace(".html", ".md")
            self.buffer = "["
        elif tag == "table":
            self.in_table = True
            self.table_rows = []
        elif tag == "tr":
            self.current_row = []
        elif tag in ("td", "th"):
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False
        elif tag == "footer":
            self.in_footer = False
        elif self.in_head or self.in_footer:
            return
        elif tag in ("h1", "h2", "h3"):
            self.output.append(self.buffer + "\n")
            self.buffer = ""
        elif tag == "p" and not self.in_table:
            self.output.append(self.buffer + "\n")
            self.buffer = ""
        elif tag == "pre":
            self.in_pre = False
            self.output.append(self.buffer + "```\n")
            self.buffer = ""
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self.output.append("\n")
        elif tag == "li":
            self.output.append(self.buffer)
            self.buffer = ""
        elif tag == "dt":
            self.in_dt = False
            self.buffer += "**"
        elif tag == "dd":
            self.in_dd = False
            self.output.append(self.buffer + "\n")
            self.buffer = ""
        elif tag == "dl":
            self.output.append("\n")
        elif tag == "code" and not self.in_pre:
            self.buffer += "`"
        elif tag == "strong":
            self.buffer += "**"
        elif tag == "a":
            self.buffer += f"]({self.link_href})"
            self.link_href = ""
        elif tag == "table":
            self.in_table = False
            self._render_table()
        elif tag == "tr":
            self.table_rows.append(self.current_row)
        elif tag in ("td", "th"):
            self.current_row.append(self.current_cell.strip())
            self.current_cell = ""

    def handle_data(self, data):
        if self.in_head or self.in_footer:
            return
        if self.in_table:
            self.current_cell += data
        elif self.in_pre:
            self.buffer += data
        else:
            cleaned = re.sub(r'\s+', ' ', data)
            self.buffer += cleaned

    def _render_table(self):
        if not self.table_rows:
            return
        self.output.append("\n")
        header = self.table_rows[0]
        self.output.append("| " + " | ".join(header) + " |\n")
        self.output.append("| " + " | ".join("---" for _ in header) + " |\n")
        for row in self.table_rows[1:]:
            padded = row + [""] * (len(header) - len(row))
            self.output.append("| " + " | ".join(padded) + " |\n")
        self.output.append("\n")

    def get_markdown(self):
        result = "".join(self.output)
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip() + "\n"


def convert_file(html_path: Path) -> str:
    content = html_path.read_text(errors="replace")

    footer_links = []
    footer_match = re.search(r'<footer>.*?<nav class="see-also">(.*?)</nav>', content, re.DOTALL)
    if footer_match:
        for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]+)', footer_match.group(1)):
            href = m.group(1).replace(".html", ".md")
            text = m.group(2)
            footer_links.append(f"[{text}]({href})")

    parser = HTMLToMarkdown()
    parser.feed(content)
    md = parser.get_markdown()

    if footer_links:
        md += f"\n---\n*See also: {', '.join(footer_links)}*\n"

    return md


def find_context_root():
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "context" / "index.html").exists():
            return parent / "context"
    if (cwd / "index.html").exists():
        return cwd
    return None


def main():
    context_dir = find_context_root()
    if not context_dir:
        context_dir = Path(__file__).parent.parent
        if not (context_dir / "index.html").exists():
            print("ERROR: No context/ directory found")
            return

    docs_dir = context_dir.parent / "docs" / "context"
    docs_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(context_dir.rglob("*.html"))
    converted = 0

    for html_file in html_files:
        md_content = convert_file(html_file)
        rel_path = html_file.relative_to(context_dir).with_suffix(".md")
        md_path = docs_dir / rel_path
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content)
        converted += 1

    print(f"Generated {converted} markdown files in {docs_dir}")


if __name__ == "__main__":
    main()
