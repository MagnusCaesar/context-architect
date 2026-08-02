import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from knowledge_graph import load_nodes, router_heads, validate_graphs  # noqa: E402
from validate import check_reachability_critical  # noqa: E402

BOOTSTRAP = SCRIPTS / "bootstrap.py"


def node(node_id, kind, status, *, parent="", children="", archived=False):
    parent_meta = f'<meta name="parent" content="{parent}">' if parent else ""
    children_meta = f'<meta name="children" content="{children}">' if children else ""
    return f"""<!doctype html><html><head>
<meta name="contract-version" content="2">
<meta name="node-id" content="{node_id}">
<meta name="kind" content="{kind}">
<meta name="status" content="{status}">
{parent_meta}{children_meta}
</head><body><article data-statement="{node_id} statement."><p class="statement">{node_id} statement.</p>""" + (
        "</article></body></html>" if archived else
        f'<a href="{children}">child</a></article></body></html>'
    )


def router(kind, links=()):
    anchors = "".join(f'<a href="{href}">{label}</a>' for href, label in links)
    return f"""<!doctype html><html><body>
<nav><a href="./{kind}.html">archive navigation</a></nav>
<section id="graph">{anchors}</section>
</body></html>"""


def graph_fixture(tmp_path):
    root = tmp_path / "context"
    files = {
        "index.html": """<html><body><a href="wiki.html">wiki</a><a href="decisions.html">decisions</a><a href="failure-todos.html">failures</a><a href="workstreams.html">work</a></body></html>""",
        "wiki.html": router("wiki"),
        "decisions.html": router("decisions", [
            ("decisions/dec-001-root.html#dec-001-root", "root"),
            ("decisions/dec-003-other.html#dec-003-other", "other"),
        ]),
        "failure-todos.html": router("failure-todos"),
        "workstreams.html": router("workstreams"),
        "decisions/dec-001-root.html": node(
            "dec-001-root", "decision", "accepted",
            children="dec-002-child.html#dec-002-child",
        ),
        "decisions/dec-002-child.html": node("dec-002-child", "decision", "accepted", parent="dec-001-root"),
        "decisions/dec-003-other.html": node("dec-003-other", "decision", "accepted"),
        "workstreams/archived/work-001.html": node("work-001", "work", "cancelled", archived=True),
        "decisions/archived/dec-004-old.html": node("dec-004-old", "decision", "deprecated", archived=True),
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def mutated_graph_fixture(tmp_path, mutation):
    root = graph_fixture(tmp_path)
    decisions = root / "decisions.html"
    content = decisions.read_text()
    if mutation == "list_child_on_router":
        content = content.replace("</section>", '<a href="decisions/dec-002-child.html#dec-002-child">child</a></section>')
    elif mutation == "omit_live_head":
        content = content.replace('<a href="decisions/dec-003-other.html#dec-003-other">other</a>', "")
    elif mutation == "link_wrong_family":
        content = content.replace("</section>", '<a href="workstreams/archived/work-001.html#work-001">work</a></section>')
    elif mutation == "list_archived_node":
        content = content.replace("</section>", '<a href="decisions/archived/dec-004-old.html#dec-004-old">old</a></section>')
    elif mutation == "remove_parent_backlink":
        child = root / "decisions/dec-002-child.html"
        child.write_text(child.read_text().replace('<meta name="parent" content="dec-001-root">', ""))
    elif mutation == "break_child_href":
        parent = root / "decisions/dec-001-root.html"
        parent.write_text(parent.read_text().replace('<a href="dec-002-child.html#dec-002-child">child</a>', ""))
    if mutation not in {"remove_parent_backlink", "break_child_href"}:
        decisions.write_text(content)
    return root


def fresh_bootstrap(tmp_path, pages=None):
    target = tmp_path / "project"
    target.mkdir()
    command = [sys.executable, str(BOOTSTRAP), "--target", str(target)]
    if pages:
        command.extend(["--pages-json", json.dumps(pages)])
    subprocess.run(command, check=True, capture_output=True, text=True)
    return target / "context"


def test_router_contains_all_and_only_live_heads(tmp_path):
    root = graph_fixture(tmp_path)
    errors = validate_graphs(root, load_nodes(root))
    assert errors == []
    assert [n.node_id for n in router_heads(root, "decision")] == ["dec-001-root", "dec-003-other"]


def test_fresh_bootstrap_routes_legacy_decision_head(tmp_path):
    root = fresh_bootstrap(tmp_path)
    assert validate_graphs(root, load_nodes(root)) == []
    assert [node.node_id for node in router_heads(root, "decision")] == ["dec-001"]


def test_fresh_bootstrap_normalizes_root_project_page_as_wiki(tmp_path):
    root = fresh_bootstrap(tmp_path, [{"name": "architecture.html", "purpose": "Architecture"}])
    nodes = load_nodes(root)
    architecture = next(node for node in nodes if node.path.name == "architecture.html")
    assert (architecture.node_id, architecture.kind, architecture.status) == ("architecture", "wiki", "active")
    assert [node.node_id for node in router_heads(root, "wiki")] == ["architecture"]
    assert validate_graphs(root, nodes) == []


def test_unreachable_legacy_root_page_is_hard_failure(tmp_path):
    root = tmp_path / "context"
    root.mkdir()
    (root / "index.html").write_text('<html><body><a href="wiki.html">wiki</a></body></html>')
    (root / "wiki.html").write_text(router("wiki"))
    (root / "orphan.html").write_text('<html><body><h1>Orphan</h1></body></html>')
    assert "orphan page: context/orphan.html" in check_reachability_critical(root)


@pytest.mark.parametrize("mutation, expected", [
    ("list_child_on_router", "router contains non-head dec-002-child"),
    ("omit_live_head", "router omits live head dec-003-other"),
    ("link_wrong_family", "decision router links work node work-001"),
    ("remove_parent_backlink", "parent/child link is not reciprocal"),
    ("list_archived_node", "router contains archived node"),
    ("break_child_href", "unreachable live node dec-002-child"),
])
def test_router_invariants(tmp_path, mutation, expected):
    root = mutated_graph_fixture(tmp_path, mutation)
    assert expected in validate_graphs(root, load_nodes(root))
