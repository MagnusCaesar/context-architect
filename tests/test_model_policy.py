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
    direct_surface_roles,
    fetch_catalog,
    refresh_policy,
    render_profiles,
    resolve_roles,
    validate_catalog,
)
import model_policy  # noqa: E402


def model(model_id, efforts=("low", "medium", "high"), default="medium", **extra):
    item = {
        "id": model_id,
        "model": model_id,
        "displayName": model_id,
        "description": f"fixture for {model_id}",
        "hidden": False,
        "isDefault": model_id == "gpt-6-astra",
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
    model("gpt-6-astra", ("low", "medium", "high", "xhigh", "max", "ultra")),
    model("gpt-6-sol", ("low", "medium", "high", "xhigh", "max", "ultra")),
    model("gpt-6-luna", ("low", "medium", "high", "xhigh", "max")),
    model("gpt-5.6-sol", ("low", "medium", "high", "xhigh", "max", "ultra")),
    model("gpt-5.6-terra", ("low", "medium", "high", "xhigh", "max", "ultra")),
]


def test_current_catalog_maps_semantic_roles():
    assert resolve_roles(CURRENT_CATALOG) == {
        "lead": ("gpt-6-astra", "high"),
        "balanced": ("gpt-6-sol", "medium"),
        "economy": ("gpt-6-luna", "medium"),
    }


def test_config_template_uses_current_policy_defaults():
    config = json.loads((ROOT / "templates" / "config.json").read_text())
    assert config["modelPolicy"] == DEFAULT_POLICY


def test_unverified_configured_slug_is_desired_not_actual():
    policy = json.loads(json.dumps(DEFAULT_POLICY)); policy["lead"]["model"] = "unverified-lead"
    roles = model_policy.direct_surface_roles(policy)
    assert roles["lead"] == ("gpt-6-sol", "high")
    assert "Desired unverified-lead/high; actual gpt-6-sol/high" in render_profiles(roles, policy)["lead.toml"]
    assert 'description = "gpt-6-sol ' in render_profiles(roles, policy)["lead.toml"]


def test_direct_surface_keeps_gpt6_and_legacy_sol_terra_pins():
    assert direct_surface_roles() == {
        "lead": ("gpt-6-astra", "high"),
        "balanced": ("gpt-6-sol", "medium"),
        "economy": ("gpt-6-luna", "medium"),
    }
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    policy["lead"] = {"model": "gpt-5.6-sol", "effort": "high"}
    policy["balanced"] = {"model": "gpt-5.6-terra", "effort": "medium"}
    assert direct_surface_roles(policy)["lead"] == ("gpt-5.6-sol", "high")
    assert direct_surface_roles(policy)["balanced"] == ("gpt-5.6-terra", "medium")


def test_unknown_direct_role_models_fall_back_to_sol_never_astra():
    policy = {"revision": "custom"}
    policy.update({role: {"model": f"unknown-{role}", "effort": "low"} for role in model_policy.ROLES})
    assert direct_surface_roles(policy) == {
        "lead": ("gpt-6-sol", "high"),
        "balanced": ("gpt-6-sol", "medium"),
        "economy": ("gpt-6-sol", "low"),
    }


@pytest.mark.parametrize("unavailable", ["missing", "rejected"])
def test_economy_unavailable_falls_back_to_sol_low_truthfully(unavailable):
    catalog = [item for item in CURRENT_CATALOG if item["model"] != "gpt-6-luna"] if unavailable == "missing" else CURRENT_CATALOG
    rejected = {"gpt-6-luna"} if unavailable == "rejected" else set()
    with pytest.warns(UserWarning, match="actual gpt-6-sol/low"):
        roles = resolve_roles(catalog, rejected_models=rejected)
    assert roles["economy"] == ("gpt-6-sol", "low")
    rendered = render_profiles(roles, requested=DEFAULT_POLICY)
    assert "actual gpt-6-sol/low" in rendered["economy.toml"]
    assert 'model = "gpt-6-sol"' in rendered["economy.toml"]


@pytest.mark.parametrize("invalid_fallback", ["missing", "hidden", "rejected", "no-low"])
def test_economy_fallback_fails_closed_when_sol_low_is_unavailable(invalid_fallback):
    catalog = [dict(item) for item in CURRENT_CATALOG]
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    policy["balanced"]["model"] = "gpt-5.6-terra"
    rejected = {"gpt-6-luna"}
    fallback = next(item for item in catalog if item["model"] == "gpt-6-sol")
    if invalid_fallback == "missing":
        catalog.remove(fallback)
    elif invalid_fallback == "hidden":
        fallback["hidden"] = True
    elif invalid_fallback == "rejected":
        rejected.add("gpt-6-sol")
    else:
        fallback["supportedReasoningEfforts"] = ["medium", "high"]
    with pytest.raises(CatalogError, match="economy model unavailable"):
        resolve_roles(catalog, policy=policy, rejected_models=rejected)


def test_unsupported_effort_uses_documented_default():
    catalog = [*CURRENT_CATALOG[:2], model("gpt-6-luna", ("low",), default="low")]
    with pytest.warns(UserWarning, match="documented default low"):
        assert resolve_roles(catalog)["economy"] == ("gpt-6-luna", "low")


@pytest.mark.parametrize(
    "bad",
    [
        [model("gpt-6-astra"), model("gpt-6-astra")],
        [{**model("gpt-6-astra"), "model": "other"}],
        [{k: v for k, v in model("gpt-6-astra").items() if k != "displayName"}],
        [{**model("gpt-6-astra"), "supportedReasoningEfforts": []}],
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


@pytest.mark.parametrize("response", ["[]", "null", '"scalar"', "17"])
def test_jsonrpc_response_must_be_an_object(response, monkeypatch, tmp_path):
    server = tmp_path / "server"
    server.write_text(
        "#!/usr/bin/env python3\nimport os,sys\nsys.stdin.readline()\nprint(os.environ['FAKE_RESPONSE'], flush=True)\n"
    )
    server.chmod(0o755); monkeypatch.setenv("FAKE_RESPONSE", response)
    with pytest.raises(CatalogError):
        fetch_catalog([str(server)], timeout=1)


def test_refresh_applies_only_explicit_available_upgrade():
    upgraded = model("gpt-5.7-sol")
    catalog = [{**CURRENT_CATALOG[0], "upgrade": {"model": "gpt-5.7-sol"}}, *CURRENT_CATALOG[1:], upgraded]
    unchanged, changes, warnings = refresh_policy(DEFAULT_POLICY, catalog, refresh=False)
    assert unchanged == DEFAULT_POLICY and not changes
    updated, changes, warnings = refresh_policy(DEFAULT_POLICY, catalog, refresh=True)
    assert updated["lead"]["model"] == "gpt-5.7-sol"
    assert changes == ["lead: gpt-6-astra -> gpt-5.7-sol"]


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


@pytest.mark.parametrize("field,value", [
    ("upgrade", []), ("upgrade", {}), ("upgrade", {"model": 7}),
    ("upgradeInfo", "gpt-5.7-sol"), ("upgradeInfo", []),
    ("upgradeInfo", {}), ("upgradeInfo", {"model": 7}),
])
def test_malformed_upgrade_metadata_is_rejected(field, value):
    catalog = [{**CURRENT_CATALOG[0], field: value}, *CURRENT_CATALOG[1:]]
    with pytest.raises(CatalogError):
        refresh_policy(DEFAULT_POLICY, catalog, refresh=True)


def _bundle_bytes(target, config_path):
    paths = [config_path, *(target / ".codex" / "agents").glob("*.toml")]
    return {path: path.read_bytes() for path in paths}


@pytest.mark.parametrize("fail_at", [2, 4])
def test_policy_bundle_rolls_back_every_file_on_replace_failure(tmp_path, fail_at):
    target, config_path = tmp_path / "project", tmp_path / "project" / "context" / "config.json"
    roles = {"lead": ("gpt-5.6-sol", "high"), "balanced": ("gpt-5.6-terra", "medium"),
             "economy": ("gpt-5.6-terra", "low")}
    old_config = {"keep": "old", "modelPolicy": DEFAULT_POLICY}
    model_policy.write_policy_bundle(target, config_path, old_config, roles, DEFAULT_POLICY)
    before = _bundle_bytes(target, config_path)
    calls = 0
    original = os.replace

    def fail_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("injected replace failure")
        original(source, destination)

    with pytest.raises(OSError, match="injected"):
        model_policy.write_policy_bundle(
            target, config_path, {"keep": "new", "modelPolicy": DEFAULT_POLICY},
            roles, DEFAULT_POLICY, replace=fail_replace,
        )
    assert _bundle_bytes(target, config_path) == before


def test_policy_bundle_conflict_preserves_observed_bytes(tmp_path):
    target, config_path = tmp_path / "project", tmp_path / "project" / "context" / "config.json"
    roles = {"lead": ("gpt-5.6-sol", "high"), "balanced": ("gpt-5.6-terra", "medium"),
             "economy": ("gpt-5.6-terra", "low")}
    model_policy.write_policy_bundle(target, config_path, {"modelPolicy": DEFAULT_POLICY}, roles, DEFAULT_POLICY)
    expected = model_policy.bundle_digests(target, config_path)
    economy = target / ".codex" / "agents" / "economy.toml"
    economy.write_text(economy.read_text() + "# concurrent author edit\n")
    before = _bundle_bytes(target, config_path)
    with pytest.raises(model_policy.PolicyConflict):
        model_policy.write_policy_bundle(
            target, config_path, {"modelPolicy": DEFAULT_POLICY}, roles, DEFAULT_POLICY,
            expected=expected,
        )
    assert _bundle_bytes(target, config_path) == before
