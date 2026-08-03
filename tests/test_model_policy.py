import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_policy import (  # noqa: E402
    CatalogError,
    DEFAULT_POLICY,
    fetch_catalog,
    refresh_policy,
    render_profiles,
    resolve_roles,
    validate_catalog,
)


def model(model_id, efforts=("low", "medium", "high"), default="medium", **extra):
    item = {
        "id": model_id,
        "model": model_id,
        "displayName": model_id,
        "description": f"fixture for {model_id}",
        "hidden": False,
        "isDefault": model_id == "gpt-5.6-sol",
        "defaultReasoningEffort": default,
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort, "description": effort} for effort in efforts
        ],
        "upgrade": None,
        "upgradeInfo": None,
    }
    item.update(extra)
    return item


CURRENT_CATALOG = [
    model("gpt-5.6-sol", ("low", "medium", "high", "xhigh", "max", "ultra")),
    model("gpt-5.6-terra", ("low", "medium", "high", "xhigh", "max", "ultra")),
    model("gpt-5.6-luna", ("low", "medium", "high", "xhigh", "max")),
]


def test_current_catalog_maps_semantic_roles():
    assert resolve_roles(CURRENT_CATALOG) == {
        "lead": ("gpt-5.6-sol", "high"),
        "balanced": ("gpt-5.6-terra", "medium"),
        "economy": ("gpt-5.6-luna", "medium"),
    }


@pytest.mark.parametrize("unavailable", ["missing", "rejected"])
def test_luna_unavailable_falls_back_truthfully(unavailable):
    catalog = CURRENT_CATALOG[:-1] if unavailable == "missing" else CURRENT_CATALOG
    rejected = {"gpt-5.6-luna"} if unavailable == "rejected" else set()
    with pytest.warns(UserWarning, match="actual gpt-5.6-terra/low"):
        roles = resolve_roles(catalog, rejected_models=rejected)
    assert roles["economy"] == ("gpt-5.6-terra", "low")
    rendered = render_profiles(roles, requested=DEFAULT_POLICY)
    assert "actual gpt-5.6-terra/low" in rendered["economy.toml"]
    assert 'model = "gpt-5.6-terra"' in rendered["economy.toml"]


def test_unsupported_effort_uses_documented_default():
    catalog = [*CURRENT_CATALOG[:2], model("gpt-5.6-luna", ("low",), default="low")]
    with pytest.warns(UserWarning, match="documented default low"):
        assert resolve_roles(catalog)["economy"] == ("gpt-5.6-luna", "low")


@pytest.mark.parametrize(
    "bad",
    [
        [model("gpt-5.6-sol"), model("gpt-5.6-sol")],
        [{**model("gpt-5.6-sol"), "model": "other"}],
        [{k: v for k, v in model("gpt-5.6-sol").items() if k != "displayName"}],
        [{**model("gpt-5.6-sol"), "supportedReasoningEfforts": []}],
    ],
)
def test_catalog_validation_rejects_ambiguous_or_incomplete_items(bad):
    with pytest.raises(CatalogError):
        validate_catalog(bad)


def _fake_server(path: Path):
    path.write_text(
        """#!/usr/bin/env python3
import json, os, sys, time
mode = os.environ.get('FAKE_MODE', 'ok')
pages = json.load(open(os.environ['FAKE_PAGES']))
seen = []
for line in sys.stdin:
    req = json.loads(line); seen.append(req)
    if mode == 'timeout': time.sleep(2); continue
    if mode == 'malformed': print('{broken', flush=True); break
    if 'id' not in req: continue
    if req.get('method') == 'initialize':
        print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':{'serverInfo':{'name':'fake','version':'1'}}}), flush=True)
    elif req.get('method') == 'model/list':
        cursor = req.get('params', {}).get('cursor')
        index = 0 if cursor is None else int(cursor)
        nxt = str(index + 1) if index + 1 < len(pages) else None
        print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':{'data':pages[index],'nextCursor':nxt}}), flush=True)
        if nxt is None: break
open(os.environ['FAKE_LOG'], 'w').write(json.dumps(seen))
"""
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_catalog_client_initializes_notifies_and_pages(monkeypatch, tmp_path):
    server, pages, log = tmp_path / "server", tmp_path / "pages.json", tmp_path / "log.json"
    _fake_server(server)
    pages.write_text(json.dumps([CURRENT_CATALOG[:2], CURRENT_CATALOG[2:]]))
    monkeypatch.setenv("FAKE_PAGES", str(pages)); monkeypatch.setenv("FAKE_LOG", str(log))
    assert fetch_catalog([str(server)], timeout=2) == CURRENT_CATALOG
    requests = json.loads(log.read_text())
    assert requests[0]["method"] == "initialize"
    assert requests[0]["params"]["capabilities"]["experimentalApi"] is True
    assert requests[1] == {"jsonrpc": "2.0", "method": "initialized", "params": {}}
    lists = [r for r in requests if r.get("method") == "model/list"]
    assert lists[0]["params"] == {"includeHidden": True, "limit": 200}
    assert lists[1]["params"]["cursor"] == "1"


@pytest.mark.parametrize("mode", ["malformed", "timeout"])
def test_catalog_client_fails_closed(mode, monkeypatch, tmp_path):
    server, pages, log = tmp_path / "server", tmp_path / "pages.json", tmp_path / "log.json"
    _fake_server(server); pages.write_text(json.dumps([CURRENT_CATALOG]))
    monkeypatch.setenv("FAKE_PAGES", str(pages)); monkeypatch.setenv("FAKE_LOG", str(log)); monkeypatch.setenv("FAKE_MODE", mode)
    with pytest.raises(CatalogError):
        fetch_catalog([str(server)], timeout=.1)


def test_missing_codex_fails_closed():
    with pytest.raises(CatalogError):
        fetch_catalog(["/definitely/missing/codex"], timeout=.1)


def test_refresh_applies_only_explicit_available_upgrade():
    upgraded = model("gpt-5.7-sol")
    catalog = [{**CURRENT_CATALOG[0], "upgrade": {"model": "gpt-5.7-sol"}}, *CURRENT_CATALOG[1:], upgraded]
    unchanged, changes, warnings = refresh_policy(DEFAULT_POLICY, catalog, refresh=False)
    assert unchanged == DEFAULT_POLICY and not changes
    updated, changes, warnings = refresh_policy(DEFAULT_POLICY, catalog, refresh=True)
    assert updated["lead"]["model"] == "gpt-5.7-sol"
    assert changes == ["lead: gpt-5.6-sol -> gpt-5.7-sol"]


@pytest.mark.parametrize(
    "source,extra",
    [
        ({"upgrade": {"model": "missing"}}, []),
        ({"upgrade": {"model": "gpt-5.7-sol"}, "upgradeInfo": {"model": "gpt-5.8-sol"}}, [model("gpt-5.7-sol"), model("gpt-5.8-sol")]),
        ({"upgrade": {"model": "gpt-5.7-sol"}}, [{**model("gpt-5.7-sol"), "hidden": True}]),
    ],
)
def test_ambiguous_unknown_or_hidden_upgrade_preserves_policy(source, extra):
    catalog = [{**CURRENT_CATALOG[0], **source}, *CURRENT_CATALOG[1:], *extra]
    updated, changes, notices = refresh_policy(DEFAULT_POLICY, catalog, refresh=True)
    assert updated == DEFAULT_POLICY and not changes and notices
