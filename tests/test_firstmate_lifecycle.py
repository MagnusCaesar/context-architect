import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from context_utils import firstmate_root, migrate_firstmate  # noqa: E402


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_neutral_root_precedence_and_legacy_warning(tmp_path):
    env = {"HOME": str(tmp_path / "home"), "XDG_DATA_HOME": str(tmp_path / "xdg")}
    assert firstmate_root(env) == tmp_path / "xdg" / "context-architecture" / "firstmate"
    env["FIRSTMATE_HOME"] = str(tmp_path / "legacy")
    with pytest.warns(FutureWarning):
        assert firstmate_root(env) == tmp_path / "legacy"
    env["CONTEXT_ARCH_FIRSTMATE"] = str(tmp_path / "preferred")
    assert firstmate_root(env) == tmp_path / "preferred"


def test_explicit_migration_copies_without_deleting_source(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    (source / "context").mkdir(parents=True)
    (source / "context" / "project-registry.html").write_text("registry")
    migrate_firstmate(source, target)
    assert (source / "context" / "project-registry.html").read_text() == "registry"
    assert (target / "context" / "project-registry.html").read_text() == "registry"


def test_migration_rejects_nested_symlink_without_reading_or_writing(tmp_path):
    source, target, outside = tmp_path / "old", tmp_path / "new", tmp_path / "private"
    (source / "context" / "nested").mkdir(parents=True)
    (source / "context" / "keep").write_text("source")
    outside.write_text("PRIVATE-DATA")
    (source / "context" / "nested" / "escape").symlink_to(outside)
    before = sorted((path.relative_to(source).as_posix(), path.is_symlink()) for path in source.rglob("*"))

    with pytest.raises(ValueError, match="symlink"):
        migrate_firstmate(source, target)

    assert sorted((path.relative_to(source).as_posix(), path.is_symlink()) for path in source.rglob("*")) == before
    assert outside.read_text() == "PRIVATE-DATA"
    assert not target.exists()


def test_migration_rejects_symlink_source_root(tmp_path):
    real, source, target = tmp_path / "real", tmp_path / "old", tmp_path / "new"
    real.mkdir()
    (real / "keep").write_text("source")
    source.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        migrate_firstmate(source, target)

    assert source.is_symlink()
    assert (real / "keep").read_text() == "source"
    assert not target.exists()


@pytest.mark.parametrize("layout", ["same", "target-inside-source", "source-inside-target"])
def test_migration_rejects_overlapping_roots_without_mutating_source(tmp_path, layout):
    source = tmp_path / "source"; source.mkdir(); marker = source / "keep"; marker.write_text("source")
    if layout == "same":
        target = source
    elif layout == "target-inside-source":
        target = source / "nested"
    else:
        target = tmp_path; source = tmp_path / "source"
    with pytest.raises(ValueError, match="overlap"):
        migrate_firstmate(source, target)
    assert marker.read_text() == "source"


def test_legacy_alias_warning_is_visible_from_cli(tmp_path):
    legacy = tmp_path / "legacy"; legacy.mkdir()
    env = dict(os.environ); env["FIRSTMATE_HOME"] = str(legacy)
    env.pop("CONTEXT_ARCH_FIRSTMATE", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "bootstrap.py"), "--scope", "global",
         "--platform", "codex", "--scan"], capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0
    assert "FIRSTMATE_HOME is deprecated" in result.stderr


@pytest.mark.parametrize("init_git", [False, True])
def test_global_bootstrap_creates_private_state_and_git_is_opt_in(tmp_path, init_git):
    target = tmp_path / ("with-git" if init_git else "without-git"); target.mkdir()
    cmd = [sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(target),
           "--scope", "global", "--platform", "codex", "--generate"]
    if init_git: cmd.append("--init-git")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    context = target / "context"
    for rel in ("project-registry.html", "capture-inbox.html", "config.json", ".validation-state.json"):
        assert (context / rel).exists(), rel
    assert (context / ".git").exists() is init_git
    assert not (ROOT / "scripts" / "wire-global-hooks.py").exists()
    assert not (ROOT / "templates" / "firstmate-review" / "SKILL.md").exists()


def test_registry_managed_block_preserves_authored_content(tmp_path):
    registry = tmp_path / "project-registry.html"
    registry.write_text("<html><body><p>authored</p><!-- context-architecture:projects:start --><!-- context-architecture:projects:end --></body></html>")
    seed = load_script("seed-registry.py")
    seed.update_registry(registry, [
        ("zeta", "/z/context", "Z", "active"),
        ("alpha", "/a/context", "A", "active"),
    ])
    text = registry.read_text()
    assert "<p>authored</p>" in text
    assert text.index("alpha") < text.index("zeta")
    assert text.count("context-architecture:projects:start") == 1


def _project(root: Path, name: str, secret: str):
    context = root / name / "context"; (context / "scripts").mkdir(parents=True)
    (context / "index.html").write_text(f"<html><body>{secret}</body></html>")
    for script in ("daily-hygiene.py", "check-reachability.py", "validate.py"):
        (context / "scripts" / script).write_text(
            "import json\nprint(json.dumps({'status':'ok','body':%r}))\n" % secret
        )
    return context


def test_review_output_is_cross_project_private(tmp_path):
    firstmate = tmp_path / "firstmate"; fm_context = firstmate / "context"; fm_context.mkdir(parents=True)
    a = _project(tmp_path, "alpha", "ALPHA_NODE_SECRET")
    b = _project(tmp_path, "beta", "BETA_CAPTURE_SECRET")
    unregistered = tmp_path / "UNREGISTERED_SECRET"
    articles = "".join(f'<article class="project">{n} | {p} | desc | active</article>' for n, p in (("alpha", a), ("beta", b)))
    (fm_context / "project-registry.html").write_text(f"<section>{articles}</section>")
    result = subprocess.run([sys.executable, str(SCRIPTS / "fm-review.py"), "--firstmate", str(firstmate), "--json"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    output = result.stdout
    for secret in ("ALPHA_NODE_SECRET", "BETA_CAPTURE_SECRET", str(unregistered)):
        assert secret not in output
    report = json.loads(output)
    assert [(p["name"], p["status"]) for p in report["projects"]] == [("alpha", "ok"), ("beta", "ok")]


def test_codex_profiles_are_concise_and_truthful(tmp_path):
    target = tmp_path / "project"; target.mkdir()
    result = subprocess.run([sys.executable, str(SCRIPTS / "bootstrap.py"), "--target", str(target), "--platform", "codex", "--generate"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    profiles = target / ".codex" / "agents"
    assert {p.name for p in profiles.glob("*.toml")} == {"lead.toml", "balanced.toml", "economy.toml"}
    for profile in profiles.glob("*.toml"):
        text = profile.read_text()
        assert all(word not in text.lower() for word in ("mutex", "ledger format", "receipt format", "graph schema", "hygiene algorithm"))
        assert "task capsule" in text.lower()
        assert "shared filesystem" in text.lower()
        assert "hook composition" in text.lower()
        assert "parent safety overrides" in text.lower()
    economy = tomllib.loads((profiles / "economy.toml").read_text())
    assert economy["model"] == "gpt-5.6-terra"
    assert economy["model_reasoning_effort"] == "low"
    assert "Desired gpt-5.6-luna/medium; actual gpt-5.6-terra/low" in economy["developer_instructions"]


def test_claude_refresh_never_adds_codex_model_policy(tmp_path):
    target = tmp_path / "claude"; target.mkdir()
    bootstrap = str(SCRIPTS / "bootstrap.py")
    generated = subprocess.run([sys.executable, bootstrap, "--target", str(target),
                                "--platform", "claude", "--generate"], capture_output=True, text=True)
    refreshed = subprocess.run([sys.executable, bootstrap, "--target", str(target),
                                "--refresh"], capture_output=True, text=True)
    assert generated.returncode == refreshed.returncode == 0
    assert "modelPolicy" not in json.loads((target / "context" / "config.json").read_text())


def test_malformed_catalog_refresh_preserves_generated_profiles(tmp_path):
    target = tmp_path / "codex"; target.mkdir()
    bootstrap = str(SCRIPTS / "bootstrap.py")
    generated = subprocess.run([sys.executable, bootstrap, "--target", str(target),
                                "--platform", "codex", "--generate"], capture_output=True, text=True)
    assert generated.returncode == 0, generated.stderr + generated.stdout
    profiles = target / ".codex" / "agents"
    before = {path.name: path.read_bytes() for path in profiles.glob("*.toml")}
    config_path = target / "context" / "config.json"
    config = json.loads(config_path.read_text()); config.pop("modelPolicy")
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    config_before = config_path.read_bytes()
    fake_bin = tmp_path / "bin"; fake_bin.mkdir()
    fake = fake_bin / "codex"; fake.write_text("#!/bin/sh\nprintf '{broken\\n'\n"); fake.chmod(0o755)
    env = dict(os.environ); env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    refreshed = subprocess.run([sys.executable, bootstrap, "--target", str(target), "--refresh"],
                               capture_output=True, text=True, env=env)
    assert refreshed.returncode == 0, refreshed.stderr + refreshed.stdout
    assert {path.name: path.read_bytes() for path in profiles.glob("*.toml")} == before
    assert config_path.read_bytes() == config_before
    assert "model policy preserved" in refreshed.stdout.lower()
