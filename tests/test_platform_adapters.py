import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from platforms import (  # noqa: E402
    PlatformError,
    install_bootloaders,
    render_bootloader,
    resolve_platform,
)


def homes(claude, codex):
    return {"claude": claude, "codex": codex}


def snapshot_tree(root):
    snapshot = []
    for path in sorted((root, *root.rglob("*")), key=lambda item: str(item)):
        stat = path.stat()
        rel = "." if path == root else path.relative_to(root).as_posix()
        snapshot.append((rel, "dir" if path.is_dir() else "file", stat.st_mtime_ns,
                         None if path.is_dir() else path.read_bytes()))
    return snapshot


def build_installer(directory):
    installer = Path(directory) / "installer.sh"
    built = subprocess.run(["bash", str(SKILL / "package.sh"), str(installer)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr + built.stdout
    return installer


@pytest.mark.parametrize("explicit, claude_home, codex_home, expected", [
    ("claude", True, True, ("claude",)),
    ("codex", True, True, ("codex",)),
    ("both", True, True, ("claude", "codex")),
    (None, False, True, ("codex",)),
    (None, True, False, ("claude",)),
])
def test_platform_resolution(explicit, claude_home, codex_home, expected):
    assert resolve_platform(explicit, {}, homes(claude_home, codex_home)) == expected


def test_ambiguous_dual_install_requires_explicit_platform():
    with pytest.raises(PlatformError, match="choose --platform claude|codex|both"):
        resolve_platform(None, {}, homes(True, True))


def test_explicit_platform_wins_over_environment():
    assert resolve_platform("codex", {"CLAUDE_CODE": "1"}, homes(True, False)) == ("codex",)


def test_authored_text_survives_bootloader_refresh_byte_for_byte():
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        agents = target / "AGENTS.md"
        before = "authored before\n"
        after = "\nauthored after\n"
        agents.write_text(before + render_bootloader("codex") + after)

        install_bootloaders(target, ("codex",))

        text = agents.read_text()
        assert text.startswith(before)
        assert text.endswith(after)


def test_bootloader_refresh_is_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        install_bootloaders(target, ("claude", "codex"))
        first = {path.name: path.read_bytes() for path in target.glob("*.md")}
        install_bootloaders(target, ("claude", "codex"))
        assert {path.name: path.read_bytes() for path in target.glob("*.md")} == first


@pytest.mark.parametrize("bad", [
    "<!-- context-architecture:start -->\n<!-- context-architecture:start -->\n<!-- context-architecture:end -->\n",
    "<!-- context-architecture:end -->\n<!-- context-architecture:start -->\n",
])
def test_malformed_markers_fail_without_writing(bad):
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        agents = target / "AGENTS.md"
        agents.write_text("authored\n" + bad)
        original = agents.read_bytes()

        with pytest.raises(PlatformError, match="managed markers"):
            install_bootloaders(target, ("codex",))

        assert agents.read_bytes() == original


def test_dual_install_preflights_all_targets_before_writing():
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        (target / "CLAUDE.md").write_text(render_bootloader("claude").replace("### Claude Code", "### Stale Claude Code"))
        (target / "AGENTS.md").write_text("<!-- context-architecture:start -->\nmalformed\n")
        before = snapshot_tree(target)

        with pytest.raises(PlatformError, match="managed markers"):
            install_bootloaders(target, ("claude", "codex"))

        assert snapshot_tree(target) == before


def test_platform_templates_do_not_leak_other_harness_vocabulary():
    claude = render_bootloader("claude")
    codex = render_bootloader("codex")

    assert "Codex" not in claude
    assert "AGENTS.md" not in claude
    assert "Claude" not in codex
    assert "/context-mode:" not in codex


def test_bootstrap_stores_platform_and_refresh_uses_it_without_detection():
    bootstrap = SCRIPTS / "bootstrap.py"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        created = subprocess.run(
            [sys.executable, str(bootstrap), "--target", str(target), "--platform", "codex"],
            capture_output=True, text=True,
        )
        assert created.returncode == 0, created.stderr + created.stdout
        assert json.loads((target / "context" / "config.json").read_text())["platform"] == "codex"
        assert (target / "AGENTS.md").exists()
        assert not (target / "CLAUDE.md").exists()

        refreshed = subprocess.run(
            [sys.executable, str(bootstrap), "--target", str(target), "--refresh"],
            capture_output=True, text=True,
        )
        assert refreshed.returncode == 0, refreshed.stderr + refreshed.stdout
        assert "new session required" in refreshed.stdout.lower()


def test_bootstrap_and_refresh_remove_unsupported_auto_commit_flag():
    bootstrap = SCRIPTS / "bootstrap.py"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        created = subprocess.run(
            [sys.executable, str(bootstrap), "--target", str(target), "--platform", "claude"],
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, created.stderr + created.stdout
        config_path = target / "context" / "config.json"
        config = json.loads(config_path.read_text())
        assert "autoCommitContext" not in config

        config["autoCommitContext"] = True
        config_path.write_text(json.dumps(config))
        refreshed = subprocess.run(
            [sys.executable, str(bootstrap), "--target", str(target), "--refresh"],
            capture_output=True,
            text=True,
        )
        assert refreshed.returncode == 0, refreshed.stderr + refreshed.stdout
        assert "autoCommitContext" not in json.loads(config_path.read_text())


def test_bootstrap_preflights_dual_markers_before_creating_context():
    bootstrap = SCRIPTS / "bootstrap.py"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        (target / "CLAUDE.md").write_text(render_bootloader("claude"))
        (target / "AGENTS.md").write_text("<!-- context-architecture:start -->\nmalformed\n")
        before = snapshot_tree(target)

        result = subprocess.run(
            [sys.executable, str(bootstrap), "--target", str(target), "--platform", "both"],
            capture_output=True, text=True,
        )

        assert result.returncode != 0
        assert "managed markers" in result.stdout
        assert snapshot_tree(target) == before


@pytest.mark.parametrize("extra", (("--generate",), ("--generate", "--init-git")))
def test_ambiguous_global_platform_leaves_nonexistent_target_unchanged(tmp_path, extra):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    target = tmp_path / "firstmate"
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("CLAUDE_CODE", None)
    env.pop("CODEX", None)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "bootstrap.py"),
            "--target",
            str(target),
            "--scope",
            "global",
            *extra,
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "choose --platform" in result.stdout
    assert not target.exists()


def test_global_refresh_failure_leaves_nonexistent_target_unchanged(tmp_path):
    target = tmp_path / "firstmate"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "bootstrap.py"),
            "--target",
            str(target),
            "--scope",
            "global",
            "--platform",
            "codex",
            "--refresh",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not target.exists()


def test_refresh_preflights_dual_markers_before_updating_machinery():
    bootstrap = SCRIPTS / "bootstrap.py"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        created = subprocess.run(
            [sys.executable, str(bootstrap), "--target", str(target), "--platform", "both"],
            capture_output=True, text=True,
        )
        assert created.returncode == 0, created.stderr + created.stdout
        (target / "CLAUDE.md").write_text(render_bootloader("claude").replace("### Claude Code", "### Stale Claude Code"))
        (target / "AGENTS.md").write_text("<!-- context-architecture:start -->\nmalformed\n")
        before = snapshot_tree(target)

        result = subprocess.run(
            [sys.executable, str(bootstrap), "--target", str(target), "--refresh"],
            capture_output=True, text=True,
        )

        assert result.returncode != 0
        assert "managed markers" in result.stdout
        assert snapshot_tree(target) == before


@pytest.mark.parametrize("platform, expected", [
    ("claude", (".claude/skills/context-architecture",)),
    ("codex", (".codex/skills/context-architecture",)),
    ("both", (".claude/skills/context-architecture", ".codex/skills/context-architecture")),
])
def test_installer_dry_run_selects_platform_without_creating_home(platform, expected):
    with tempfile.TemporaryDirectory() as directory:
        installer = build_installer(directory)
        observed = Path(directory) / "observed"
        home = observed / "home"
        temp_root = observed / "tmp"
        home.mkdir(parents=True)
        temp_root.mkdir()
        (home / "sentinel").write_text("home")
        (temp_root / "sentinel").write_text("tmp")
        before = snapshot_tree(observed)
        env = dict(os.environ, HOME=str(home), TMPDIR=str(temp_root))
        result = subprocess.run(
            ["bash", str(installer), "--dry-run", "--platform", platform],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert all(path in result.stdout for path in expected)
        assert snapshot_tree(observed) == before


def test_installer_requires_explicit_platform_before_any_write():
    with tempfile.TemporaryDirectory() as directory:
        installer = build_installer(directory)
        observed = Path(directory) / "observed"
        home = observed / "home"
        temp_root = observed / "tmp"
        home.mkdir(parents=True)
        temp_root.mkdir()
        before = snapshot_tree(observed)
        env = dict(os.environ, HOME=str(home), TMPDIR=str(temp_root))

        result = subprocess.run(["bash", str(installer), "--dry-run"], capture_output=True, text=True, env=env)

        assert result.returncode == 2
        assert "--platform" in result.stderr
        assert snapshot_tree(observed) == before
