import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from knowledge_graph import heads, load_nodes, validate_graphs  # noqa: E402


WORK_NODE_HTML = """<!doctype html><html><head>
<meta name="contract-version" content="2">
<meta name="node-id" content="work-001-release">
<meta name="kind" content="work">
<meta name="status" content="active">
</head><body><article data-statement="Ship a reproducible tagged package."></article></body></html>"""

LEGACY_QUESTION_HTML = """<!doctype html><html><head>
<meta name="status" content="backlog">
</head><body><article id="question-001-api"><p>Which API is stable?</p></article></body></html>"""

LEGACY_DECISION_HTML = """<!doctype html><html><head>
<meta name="status" content="accepted">
</head><body><article class="decision" id="dec-001-cache"><p>Use the existing cache.</p></article></body></html>"""

LEGACY_FAILURE_HTML = """<!doctype html><html><head>
<meta name="status" content="blocked">
</head><body><article id="failure-001-cache"><p>Cache invalidation is blocked.</p></article></body></html>"""


def write_context(tmp_path, files):
    root = tmp_path / "context"
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def test_v2_work_node_parses_minimal_contract(tmp_path):
    root = write_context(tmp_path, {
        "workstreams/work-001-release.html": WORK_NODE_HTML,
    })
    node = load_nodes(root)[0]
    assert (node.node_id, node.kind, node.status) == (
        "work-001-release", "work", "active"
    )
    assert node.parent is None
    assert node.statement == "Ship a reproducible tagged package."


def test_v2_document_with_multiple_articles_emits_one_node(tmp_path):
    root = write_context(tmp_path, {
        "workstreams/work-001-release.html": WORK_NODE_HTML.replace(
            "</body>", '<article id="unrelated">Not another graph node.</article></body>'
        ),
    })
    assert [node.node_id for node in load_nodes(root)] == ["work-001-release"]


def test_legacy_open_question_normalizes_as_work_question(tmp_path):
    root = write_context(tmp_path, {
        "open-questions/question-001-api.html": LEGACY_QUESTION_HTML,
    })
    node = load_nodes(root)[0]
    assert node.kind == "work"
    assert node.status == "backlog"


def test_legacy_decision_and_failure_remain_readable(tmp_path):
    root = write_context(tmp_path, {
        "decisions/dec-001-cache.html": LEGACY_DECISION_HTML,
        "failure-todos/failure-001-cache.html": LEGACY_FAILURE_HTML,
    })
    assert [(node.node_id, node.kind, node.status) for node in load_nodes(root)] == [
        ("dec-001-cache", "decision", "accepted"),
        ("failure-001-cache", "failure", "blocked"),
    ]


def test_legacy_root_decision_normalizes_without_moving_the_page(tmp_path):
    root = write_context(tmp_path, {"decisions.html": LEGACY_DECISION_HTML})
    assert [(node.node_id, node.kind, node.status) for node in load_nodes(root)] == [
        ("dec-001-cache", "decision", "accepted"),
    ]


def test_archive_indexes_are_not_nodes(tmp_path):
    root = write_context(tmp_path, {
        "decisions/archive.html": "<html><head></head><body></body></html>",
    })
    assert load_nodes(root) == []


def test_v2_nodes_cover_each_graph_family(tmp_path):
    root = write_context(tmp_path, {
        "wiki/wiki-001-overview.html": v2_node("wiki-001-overview", "wiki", "active"),
        "decisions/dec-001-cache.html": v2_node("dec-001-cache", "decision", "accepted"),
        "failure-todos/failure-001-cache.html": v2_node("failure-001-cache", "failure", "open"),
        "workstreams/work-001-release.html": v2_node("work-001-release", "work", "active"),
    })
    nodes = load_nodes(root)
    assert [(node.node_id, node.kind, node.status) for node in nodes] == [
        ("dec-001-cache", "decision", "accepted"),
        ("failure-001-cache", "failure", "open"),
        ("wiki-001-overview", "wiki", "active"),
        ("work-001-release", "work", "active"),
    ]
    assert [node.node_id for node in heads(nodes, "work")] == ["work-001-release"]


def v2_node(node_id, kind, status, statement="A durable statement.", **fields):
    data = " ".join(
        f'data-{name.replace("_", "-") }="{value}"'
        for name, value in fields.items() if value is not None
    )
    statement_attr = f' data-statement="{statement}"' if statement is not None else ""
    return f"""<!doctype html><html><head>
<meta name="contract-version" content="2">
<meta name="node-id" content="{node_id}">
<meta name="kind" content="{kind}">
<meta name="status" content="{status}">
</head><body><article{statement_attr} {data}></article></body></html>"""


INVALID_CASES = {
    "duplicate id": "duplicate node id dec-001-cache",
    "invalid status": "invalid work status proposed",
    "empty statement": "missing durable statement",
    "unknown child": "unknown child work-999-missing",
    "cross-family parent": "work node parent must be work",
    "archived parent": "live node cannot use archived parent",
    "one-sided link": "parent/child link is not reciprocal",
    "parent cycle": "parent cycle",
    "wrong directory": "decision node stored outside decisions",
}


def invalid_files(case):
    if case == "duplicate id":
        return {
            "decisions/dec-001-cache.html": v2_node("dec-001-cache", "decision", "accepted"),
            "decisions/dec-002-copy.html": v2_node("dec-001-cache", "decision", "accepted"),
        }
    if case == "invalid status":
        return {"workstreams/work-001-release.html": v2_node("work-001-release", "work", "proposed")}
    if case == "empty statement":
        return {"workstreams/work-001-release.html": v2_node("work-001-release", "work", "active", statement=None)}
    if case == "unknown child":
        return {"workstreams/work-001-release.html": v2_node("work-001-release", "work", "active", children="work-999-missing")}
    if case == "cross-family parent":
        return {
            "decisions/dec-001-cache.html": v2_node("dec-001-cache", "decision", "accepted", children="work-001-release"),
            "workstreams/work-001-release.html": v2_node("work-001-release", "work", "active", parent="dec-001-cache"),
        }
    if case == "archived parent":
        return {
            "workstreams/archive/work-001-old.html": v2_node("work-001-old", "work", "done", children="work-002-live"),
            "workstreams/work-002-live.html": v2_node("work-002-live", "work", "active", parent="work-001-old"),
        }
    if case == "one-sided link":
        return {
            "workstreams/work-001-parent.html": v2_node("work-001-parent", "work", "active", children="work-002-child"),
            "workstreams/work-002-child.html": v2_node("work-002-child", "work", "active"),
        }
    if case == "parent cycle":
        return {
            "workstreams/work-001-a.html": v2_node("work-001-a", "work", "active", parent="work-002-b", children="work-002-b"),
            "workstreams/work-002-b.html": v2_node("work-002-b", "work", "active", parent="work-001-a", children="work-001-a"),
        }
    if case == "wrong directory":
        return {"workstreams/dec-001-cache.html": v2_node("dec-001-cache", "decision", "accepted")}
    raise AssertionError(case)


def test_v2_graph_diagnostics_are_literal_and_non_mutating(tmp_path):
    for case, expected in INVALID_CASES.items():
        root = write_context(tmp_path / case.replace(" ", "-"), invalid_files(case))
        before = {path: path.read_bytes() for path in root.rglob("*.html")}
        assert expected in validate_graphs(root, load_nodes(root)), case
        assert before == {path: path.read_bytes() for path in root.rglob("*.html")}, case


def test_graph_diagnostics_sort_by_path_then_message(tmp_path):
    root = write_context(tmp_path, {
        "workstreams/work-002-status.html": v2_node("work-002-status", "work", "proposed"),
        "workstreams/work-001-empty.html": v2_node("work-001-empty", "work", "active", statement=None),
    })
    assert validate_graphs(root, load_nodes(root)) == [
        "missing durable statement",
        "invalid work status proposed",
    ]


def test_v2_links_require_existing_file_and_fragment(tmp_path):
    root = write_context(tmp_path, {
        "workstreams/work-001-source.html": v2_node(
            "work-001-source", "work", "active",
            related="missing.html#work-999-missing,work-002-target.html#work-999-missing",
            tracks="src/**/*.py",
        ),
        "workstreams/work-002-target.html": v2_node("work-002-target", "work", "active"),
    })
    assert validate_graphs(root, load_nodes(root)) == [
        "missing link file missing.html",
        "missing link fragment work-999-missing",
    ]


def test_v2_node_requires_canonical_family_root(tmp_path):
    root = write_context(tmp_path, {
        "misc/decisions/dec-001-cache.html": v2_node("dec-001-cache", "decision", "accepted"),
    })
    assert validate_graphs(root, load_nodes(root)) == [
        "decision node stored outside decisions",
    ]
