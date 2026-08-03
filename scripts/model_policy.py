#!/usr/bin/env python3
"""Codex model catalog, semantic role policy, and generated agent profiles."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import selectors
import subprocess
import tempfile
import time
import tomllib
import warnings
from pathlib import Path

POLICY_REVISION = "2026-08-02.1"
DEFAULT_POLICY = {
    "revision": POLICY_REVISION,
    "lead": {"model": "gpt-5.6-sol", "effort": "high"},
    "balanced": {"model": "gpt-5.6-terra", "effort": "medium"},
    "economy": {"model": "gpt-5.6-luna", "effort": "medium"},
}
ROLES = ("lead", "balanced", "economy")
DIRECT_REJECTED_MODELS = frozenset({"gpt-5.6-luna"})
DIRECT_SUPPORTED_MODELS = frozenset({"gpt-5.6-sol", "gpt-5.6-terra"})
REQUIRED_FIELDS = ("id", "model", "displayName", "hidden", "isDefault",
                   "defaultReasoningEffort", "supportedReasoningEfforts")
TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "agents"


class CatalogError(RuntimeError):
    pass


class PolicyConflict(RuntimeError):
    pass


def _efforts(item: dict) -> tuple[str, ...]:
    raw = item.get("supportedReasoningEfforts")
    if not isinstance(raw, list):
        raise CatalogError(f"{item.get('model', '<unknown>')}: supportedReasoningEfforts must be a list")
    result = []
    for entry in raw:
        effort = entry if isinstance(entry, str) else entry.get("reasoningEffort") if isinstance(entry, dict) else None
        if not isinstance(effort, str) or not effort:
            raise CatalogError(f"{item.get('model', '<unknown>')}: invalid reasoning effort")
        if effort in result:
            raise CatalogError(f"{item.get('model', '<unknown>')}: duplicate reasoning effort {effort}")
        result.append(effort)
    if not result:
        raise CatalogError(f"{item.get('model', '<unknown>')}: no supported reasoning efforts")
    if item.get("defaultReasoningEffort") not in result:
        raise CatalogError(f"{item.get('model', '<unknown>')}: default reasoning effort is unsupported")
    return tuple(result)


def validate_catalog(items: list[dict]) -> dict[str, dict]:
    if not isinstance(items, list):
        raise CatalogError("model/list data must be a list")
    catalog, ids = {}, set()
    for item in items:
        if not isinstance(item, dict):
            raise CatalogError("model/list item must be an object")
        missing = [key for key in REQUIRED_FIELDS if key not in item]
        if missing:
            raise CatalogError(f"model/list item missing {', '.join(missing)}")
        if not all(isinstance(item[key], str) and item[key] for key in ("id", "model", "displayName", "defaultReasoningEffort")):
            raise CatalogError("model/list identity and effort fields must be non-empty strings")
        if not isinstance(item["hidden"], bool) or not isinstance(item["isDefault"], bool):
            raise CatalogError(f"{item['model']}: hidden/isDefault must be booleans")
        if item["id"] in ids or item["model"] in catalog:
            raise CatalogError(f"duplicate model id: {item['model']}")
        if item["id"] != item["model"]:
            raise CatalogError(f"model id mismatch: {item['id']} != {item['model']}")
        _efforts(item)
        _upgrade_target(item.get("upgrade"), "upgrade")
        _upgrade_target(item.get("upgradeInfo"), "upgradeInfo")
        ids.add(item["id"]); catalog[item["model"]] = item
    return catalog


def resolve_roles(items: list[dict], policy: dict | None = None,
                  rejected_models: set[str] | None = None) -> dict[str, tuple[str, str]]:
    catalog = validate_catalog(items)
    policy, rejected = policy or DEFAULT_POLICY, rejected_models or set()
    resolved = {}
    for role in ROLES:
        requested = policy[role]
        slug, effort = requested["model"], requested["effort"]
        item = catalog.get(slug)
        unavailable = not item or item["hidden"] or slug in rejected
        if unavailable and role == "economy":
            fallback = catalog.get("gpt-5.6-terra")
            if fallback and not fallback["hidden"] and "gpt-5.6-terra" not in rejected and "low" in _efforts(fallback):
                warnings.warn(f"economy requested {slug}/{effort} unavailable; actual gpt-5.6-terra/low", UserWarning)
                resolved[role] = ("gpt-5.6-terra", "low")
                continue
        if unavailable:
            raise CatalogError(f"{role} model unavailable: {slug}")
        supported = _efforts(item)
        if effort not in supported:
            actual = item["defaultReasoningEffort"]
            warnings.warn(f"{role} requested unsupported effort {effort}; using documented default {actual}", UserWarning)
            effort = actual
        resolved[role] = (slug, effort)
    return resolved


def _upgrade_target(value, field: str) -> str | None:
    if value is None:
        return None
    if field == "upgrade" and isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        model = value.get("model")
        if isinstance(model, str) and model:
            return model
    raise CatalogError(f"{field} metadata is malformed")


def refresh_policy(current: dict, items: list[dict], refresh: bool) -> tuple[dict, list[str], list[str]]:
    catalog = validate_catalog(items)
    updated, changes, notices = copy.deepcopy(current), [], []
    if not refresh:
        return updated, changes, notices
    for role in ROLES:
        configured = updated.get(role, {})
        source = catalog.get(configured.get("model"))
        if not source:
            notices.append(f"{role}: configured model unavailable; preserved"); continue
        direct = _upgrade_target(source.get("upgrade"), "upgrade")
        info = _upgrade_target(source.get("upgradeInfo"), "upgradeInfo")
        if direct and info and direct != info:
            notices.append(f"{role}: conflicting upgrade targets; preserved"); continue
        target_slug = direct or info
        if not target_slug:
            continue
        target = catalog.get(target_slug)
        if not target or target["hidden"]:
            notices.append(f"{role}: upgrade target {target_slug} unavailable; preserved"); continue
        effort = configured.get("effort")
        if effort not in _efforts(target):
            effort = target["defaultReasoningEffort"]
            notices.append(f"{role}: upgrade uses documented default effort {effort}")
        old = configured["model"]
        configured.update(model=target_slug, effort=effort)
        changes.append(f"{role}: {old} -> {target_slug}")
    return updated, changes, notices


def _rpc_line(proc: subprocess.Popen, selector, request: dict, deadline: float) -> dict:
    proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n"); proc.stdin.flush()
    wanted = request.get("id")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not selector.select(remaining):
            raise CatalogError("codex app-server timed out")
        line = proc.stdout.readline()
        if not line:
            detail = proc.stderr.read(400).strip() if proc.poll() is not None else ""
            raise CatalogError("codex app-server exited before JSON-RPC" + (f": {detail}" if detail else ""))
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CatalogError("codex app-server returned malformed JSON-RPC") from exc
        if not isinstance(response, dict):
            raise CatalogError("codex app-server JSON-RPC response must be an object")
        if response.get("id") != wanted:
            continue
        if response.get("error"):
            raise CatalogError(f"codex app-server error: {response['error']}")
        if "result" not in response:
            raise CatalogError("codex app-server response missing result")
        return response["result"]


def fetch_catalog(command: list[str] | None = None, timeout: float = 10.0) -> list[dict]:
    command = command or ["codex", "app-server", "--stdio"]
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
    except (FileNotFoundError, OSError) as exc:
        raise CatalogError(f"Codex unavailable: {exc}") from exc
    selector = selectors.DefaultSelector(); selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        _rpc_line(proc, selector, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"clientInfo": {"name": "context-architecture", "version": POLICY_REVISION},
                       "capabilities": {"experimentalApi": True}}}, deadline)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}) + "\n"); proc.stdin.flush()
        data, cursor, seen = [], None, set()
        for request_id in range(2, 102):
            params = {"includeHidden": True, "limit": 200}
            if cursor is not None:
                params["cursor"] = cursor
            result = _rpc_line(proc, selector, {"jsonrpc": "2.0", "id": request_id,
                "method": "model/list", "params": params}, deadline)
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise CatalogError("model/list result missing data")
            data.extend(result["data"]); cursor = result.get("nextCursor")
            if cursor is None:
                validate_catalog(data); return data
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise CatalogError("model/list pagination cursor is invalid")
            seen.add(cursor)
        raise CatalogError("model/list exceeded page limit")
    finally:
        selector.close()
        try: proc.stdin.close()
        except OSError: pass
        try: proc.wait(timeout=.25)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()


def render_profiles(roles: dict[str, tuple[str, str]], requested: dict | None = None) -> dict[str, str]:
    requested, rendered = requested or DEFAULT_POLICY, {}
    for role in ROLES:
        slug, effort = roles[role]; wanted = requested[role]
        desired = f"{wanted['model']}/{wanted['effort']}"
        actual = f"{slug}/{effort}"
        rendered[f"{role}.toml"] = (TEMPLATES / f"{role}.toml").read_text().format(
            model=slug, effort=effort, desired=desired, actual=actual)
    return rendered


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def direct_surface_roles(policy: dict | None = None) -> dict[str, tuple[str, str]]:
    """Conservative defaults for the currently verified direct-subagent surface."""
    policy = policy or DEFAULT_POLICY
    roles = {role: (policy[role]["model"], policy[role]["effort"]) for role in ROLES}
    fallbacks = {"lead": ("gpt-5.6-sol", "high"), "balanced": ("gpt-5.6-terra", "medium"),
                 "economy": ("gpt-5.6-terra", "low")}
    for role in ROLES:
        if roles[role][0] not in DIRECT_SUPPORTED_MODELS:
            roles[role] = fallbacks[role]
    return roles


def _bundle_paths(target: Path, config_path: Path | None = None) -> list[Path]:
    agents = target / ".codex" / "agents"
    paths = [agents / f"{role}.toml" for role in ROLES]
    return paths + ([Path(config_path)] if config_path else [])


def bundle_digests(target: Path, config_path: Path) -> dict[str, str | None]:
    return {str(path.resolve()): _digest(path) for path in _bundle_paths(target, config_path)}


def _stage(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content); handle.flush(); os.fsync(handle.fileno())
        return Path(handle.name)


def _validate_bundle(contents: dict[Path, bytes]) -> None:
    for path, content in contents.items():
        try:
            parsed = json.loads(content) if path.name == "config.json" else tomllib.loads(content.decode())
        except (UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"invalid staged {path.name}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"invalid staged {path.name}: expected object")
        if path.suffix == ".toml" and not all(key in parsed for key in ("name", "model", "model_reasoning_effort", "sandbox_mode", "developer_instructions")):
            raise ValueError(f"invalid staged {path.name}: missing agent fields")


def _replace_bundle(contents: dict[Path, bytes], expected=None, replace=os.replace) -> list[Path]:
    """Stage, validate, compare-and-swap, and roll back one generated bundle."""
    _validate_bundle(contents)
    originals = {path: path.read_bytes() if path.exists() else None for path in contents}
    baseline = {str(path.resolve()): _digest(path) for path in contents}
    if expected is not None and any(baseline[key] != expected.get(key) for key in baseline):
        raise PolicyConflict("model policy bundle changed concurrently")
    staged = {path: _stage(path, content) for path, content in contents.items()}
    replaced = []
    try:
        if any(_digest(path) != baseline[str(path.resolve())] for path in contents):
            raise PolicyConflict("model policy bundle changed during staging")
        for path, temporary in staged.items():
            replace(temporary, path); replaced.append(path)
        return list(contents)
    except Exception:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(_stage(path, original), path)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def write_profiles(target: Path, roles: dict[str, tuple[str, str]], requested: dict | None = None,
                   expected: dict[str, str | None] | None = None) -> list[Path]:
    rendered = render_profiles(roles, requested=requested)
    paths = _bundle_paths(target)
    contents = {path: rendered[path.name].encode() for path in paths}
    normalized = None
    if expected is not None:
        normalized = {str(path.resolve()): expected.get(str(path.resolve()), expected.get(path.name)) for path in paths}
    return _replace_bundle(contents, expected=normalized)


def write_policy_bundle(target: Path, config_path: Path, config: dict,
                        roles: dict[str, tuple[str, str]], requested: dict | None = None,
                        expected=None, replace=os.replace) -> list[Path]:
    rendered = render_profiles(roles, requested=requested)
    paths = _bundle_paths(target, config_path)
    contents = {path: (json.dumps(config, indent=2) + "\n").encode() if path == config_path
                else rendered[path.name].encode() for path in paths}
    return _replace_bundle(contents, expected=expected, replace=replace)
