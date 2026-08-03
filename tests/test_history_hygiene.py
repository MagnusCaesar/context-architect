import hashlib
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from context_utils import run_daily_hygiene  # noqa: E402
import bootstrap  # noqa: E402
from knowledge_graph import (  # noqa: E402
    Node,
    consolidation_candidates,
    load_nodes,
    render_history,
    validate_graphs,
)


def node_html(node_id, kind, status, archived_at, *, affects="", topic="", source_owner="", body=""):
    optional = "".join(
        f'<meta name="{name}" content="{value}">'
        for name, value in (
            ("affects", affects),
            ("topic", topic),
            ("source-owner", source_owner),
        )
        if value
    )
    return f"""<!doctype html><html><head>
<meta name="contract-version" content="2">
<meta name="node-id" content="{node_id}">
<meta name="kind" content="{kind}">
<meta name="status" content="{status}">
<meta name="archived-at" content="{archived_at}">
{optional}</head><body><article data-statement="{node_id} statement">{body}</article></body></html>"""


def write_node(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def graph_node(
    node_id,
    *,
    kind="decision",
    status="accepted",
    affects=(),
    topic="",
    source_owner="",
    statement="shared cache words",
):
    return Node(
        node_id=node_id,
        kind=kind,
        status=status,
        path=Path("decisions") / f"{node_id}.html",
        archived=False,
        archived_at="",
        parent=None,
        children=(),
        related=(),
        tracks=(),
        affects=tuple(affects),
        topic=topic,
        source_owner=source_owner,
        statement=statement,
    )


def heads_with_affects(target, count):
    return [graph_node(f"dec-{index:03d}-{suffix}", affects=(target,)) for index, suffix in zip(range(1, count + 1), "abc")]


def test_history_is_terminal_archived_link_index_sorted_by_timestamp_then_id(tmp_path):
    root = tmp_path / "context"
    fixtures = {
        "wiki/archived/wiki-002.html": ("wiki-002", "wiki", "deprecated", "2026-05-03T00:00:00Z"),
        "decisions/archived/dec-002.html": ("dec-002", "decision", "superseded", "2026-05-01T00:00:00Z"),
        "failure-todos/archived/fail-001.html": ("fail-001", "failure", "resolved", "2026-05-02T00:00:00Z"),
        "workstreams/archived/work-001.html": ("work-001", "work", "done", "2026-05-01T00:00:00Z"),
        "failure-todos/archived/fail-open.html": ("fail-open", "failure", "open", "2026-04-01T00:00:00Z"),
        "workstreams/work-live.html": ("work-live", "work", "done", "2026-04-01T00:00:00Z"),
    }
    for relative, (node_id, kind, status, archived_at) in fixtures.items():
        write_node(root, relative, node_html(node_id, kind, status, archived_at, body="BODY MUST NOT BE COPIED"))

    rendered = render_history(load_nodes(root))

    assert [rendered.index(node_id) for node_id in ("dec-002", "work-001", "fail-001", "wiki-002")] == sorted(
        rendered.index(node_id) for node_id in ("dec-002", "work-001", "fail-001", "wiki-002")
    )
    assert 'href="decisions/archived/dec-002.html#dec-002"' in rendered
    assert 'href="workstreams/archived/work-001.html#work-001"' in rendered
    assert "fail-open" not in rendered
    assert "work-live" not in rendered
    assert "BODY MUST NOT BE COPIED" not in rendered


def test_malformed_archived_at_has_one_path_specific_error(tmp_path):
    root = tmp_path / "context"
    path = write_node(
        root,
        "decisions/archived/dec-bad.html",
        node_html("dec-bad", "decision", "rejected", "yesterday"),
    )

    assert validate_graphs(root, load_nodes(root)) == [
        f"{path.relative_to(root).as_posix()}: invalid archived-at timestamp yesterday"
    ]


def test_v2_terminal_archive_requires_archived_at(tmp_path):
    root = tmp_path / "context"
    path = write_node(
        root,
        "decisions/archived/dec-missing.html",
        node_html("dec-missing", "decision", "rejected", ""),
    )

    assert validate_graphs(root, load_nodes(root)) == [
        f"{path.relative_to(root).as_posix()}: missing archived-at timestamp"
    ]


def test_legacy_terminal_archive_also_requires_literal_timestamp(tmp_path):
    root = tmp_path / "context"
    path = write_node(
        root,
        "decisions/archived/legacy.html",
        '<html><body><article class="decision" data-id="dec-legacy" data-status="rejected">legacy</article></body></html>',
    )

    nodes = load_nodes(root)

    assert [node.node_id for node in nodes] == ["dec-legacy"]
    assert validate_graphs(root, nodes) == [
        f"{path.relative_to(root).as_posix()}: missing archived-at timestamp"
    ]
    assert render_history(nodes) == ""


def test_history_sorts_offset_timestamps_by_instant_then_id(tmp_path):
    root = tmp_path / "wiki" / "context"
    write_node(
        root,
        "decisions/archived/dec-a.html",
        node_html("dec-a", "decision", "rejected", "2026-05-01T00:00:00Z"),
    )
    write_node(
        root,
        "decisions/archived/dec-b.html",
        node_html("dec-b", "decision", "rejected", "2026-05-01T01:00:00+02:00"),
    )

    rendered = render_history(load_nodes(root))

    assert rendered.index("dec-b") < rendered.index("dec-a")
    assert 'href="decisions/archived/dec-a.html#dec-a"' in rendered


def test_three_heads_with_exact_affects_target_form_one_candidate():
    assert consolidation_candidates(heads_with_affects("src/cache.py", count=3)) == ({
        "basis": "affects:src/cache.py",
        "node_ids": ("dec-001-a", "dec-002-b", "dec-003-c"),
    },)


def test_two_heads_do_not_form_candidate():
    assert consolidation_candidates(heads_with_affects("src/cache.py", 2)) == ()


def test_exact_explicit_topic_and_source_owner_are_supported():
    topic = [graph_node(f"dec-topic-{index}", topic="cache-consistency") for index in range(3)]
    owner = [graph_node(f"dec-owner-{index}", source_owner="src/cache/") for index in range(3)]
    assert consolidation_candidates(topic) == ({
        "basis": "topic:cache-consistency",
        "node_ids": ("dec-topic-0", "dec-topic-1", "dec-topic-2"),
    },)
    assert consolidation_candidates(owner) == ({
        "basis": "source-owner:src/cache/",
        "node_ids": ("dec-owner-0", "dec-owner-1", "dec-owner-2"),
    },)


def test_case_different_paths_and_shared_words_do_not_merge():
    case_different = [
        graph_node("dec-001-a", affects=("src/cache.py",), statement="Choose cache policy"),
        graph_node("dec-002-b", affects=("SRC/cache.py",), statement="Choose cache shape"),
        graph_node("dec-003-c", affects=("src/Cache.py",), statement="Choose cache owner"),
    ]
    titles_only = [graph_node(f"dec-title-{index}", statement=f"Shared generic cache word {index}") for index in range(3)]
    assert consolidation_candidates(case_different) == ()
    assert consolidation_candidates(titles_only) == ()


def test_invalid_kind_and_status_never_form_or_extend_candidates():
    valid = heads_with_affects("src/cache.py", 3)
    invalid = [
        *(graph_node(f"unknown-{index}", kind="unknown", affects=("src/cache.py",)) for index in range(3)),
        graph_node("dec-invalid-status", status="hallucinated", affects=("src/cache.py",)),
    ]

    assert consolidation_candidates(invalid) == ()
    assert consolidation_candidates(valid + invalid) == ({
        "basis": "affects:src/cache.py",
        "node_ids": ("dec-001-a", "dec-002-b", "dec-003-c"),
    },)


def test_hygiene_never_rewrites_authored_nodes_and_records_candidates(tmp_path):
    root = tmp_path / "context"
    write_node(root, "index.html", '<html><body><a href="decisions.html">decisions</a></body></html>')
    links = []
    for index, suffix in zip(range(1, 4), "abc"):
        node_id = f"dec-{index:03d}-{suffix}"
        relative = f"decisions/{node_id}.html"
        write_node(root, relative, node_html(node_id, "decision", "accepted", "", affects="src/cache.py"))
        links.append(f'<a href="{relative}#{node_id}">{node_id}</a>')
    for index in range(3):
        write_node(
            root,
            f"decisions/unknown-{index}.html",
            node_html(f"unknown-{index}", "unknown", "active", "", affects="src/cache.py"),
        )
    write_node(
        root,
        "decisions/dec-invalid-status.html",
        node_html("dec-invalid-status", "decision", "hallucinated", "", affects="src/cache.py"),
    )
    write_node(root, "decisions.html", f'<html><body><section id="graph">{"".join(links)}</section></body></html>')
    write_node(root, "history.html", '<html><body><section id="history"><h2>History</h2><ul></ul></section></body></html>')
    write_node(root, "ledger.html", '<html><body><section id="events"><table><tbody>\n</tbody></table></section></body></html>')
    authored = sorted((root / "decisions").glob("*.html"))
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in authored}

    result = run_daily_hygiene(root)

    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in authored} == before
    assert result["consolidation_candidates"] == ({
        "basis": "affects:src/cache.py",
        "node_ids": ("dec-001-a", "dec-002-b", "dec-003-c"),
    },)
    event = json.loads((root / "ledger-events.ndjson").read_text().splitlines()[-1])
    assert event["extra_attrs"]["consolidation_count"] == "1"
    assert event["extra_attrs"]["consolidation_node_ids"] == "dec-001-a,dec-002-b,dec-003-c"
    expected_candidates = ({
        "basis": "affects:src/cache.py",
        "node_ids": ("dec-001-a", "dec-002-b", "dec-003-c"),
    },)
    expected_signature = hashlib.sha256(
        json.dumps(expected_candidates, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert event["extra_attrs"]["consolidation_signature"] == expected_signature


def test_bootstrap_regenerates_history_after_writing_pages(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bootstrap, "generate_history", lambda root: calls.append(root))

    context_root = bootstrap.generate_skeleton(tmp_path, [], config={})

    assert calls == [context_root]
