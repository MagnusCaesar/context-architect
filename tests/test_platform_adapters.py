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


@pytest.mark.parametrize("platform, expected", [
    ("claude", (".claude/skills/context-architecture",)),
    ("codex", (".codex/skills/context-architecture",)),
    ("both", (".claude/skills/context-architecture", ".codex/skills/context-architecture")),
])
def test_installer_dry_run_selects_platform_without_creating_home(platform, expected):
    with tempfile.TemporaryDirectory() as directory:
        installer = Path(directory) / "installer.sh"
        built = subprocess.run(["bash", str(SKILL / "package.sh"), str(installer)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr + built.stdout
        home = Path(directory) / "home"
        env = dict(os.environ, HOME=str(home))
        result = subprocess.run(
            ["bash", str(installer), "--dry-run", "--platform", platform],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert all(path in result.stdout for path in expected)
        assert not home.exists()
