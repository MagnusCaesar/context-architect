import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1]
TAG = "v1.2.3"


def run(args, cwd, *, env=None):
    return subprocess.run(
        args,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
    )


def git(repo, *args):
    completed = run(["git", *args], repo)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def init_release_repo(tmp_path):
    repo = tmp_path / "release"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SOURCE / "package.sh", repo / "package.sh")
    shutil.copy2(SOURCE / "installer-header.sh", repo / "installer-header.sh")
    (repo / "scripts" / "release-verify.py").write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "raise SystemExit(17 if os.environ.get('FAIL_VERIFY') else 0)\n"
    )
    (repo / "README.md").write_text("# fixture\n")
    (repo / ".gitignore").write_text("dist/\n")
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{TAG}] - 2026-08-02\n\n- Fixture.\n")
    (repo / "payload.txt").write_text("tracked payload\n")
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Release Test")
    git(repo, "config", "user.email", "release@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "fixture")
    git(repo, "tag", TAG)
    return repo


def package(repo, tag=TAG, **env):
    return run(["bash", "package.sh", tag], repo, env=env)


def retag_head(repo):
    git(repo, "tag", "-d", TAG)
    git(repo, "tag", TAG)


def artifacts(repo, tag=TAG):
    stem = repo / "dist" / f"contarch-{tag}"
    return Path(f"{stem}.sh"), Path(f"{stem}.tar.gz"), Path(f"{stem}.sha256")


def assert_no_completed_artifacts(repo, tag=TAG):
    assert not any(path.exists() for path in artifacts(repo, tag))


@pytest.mark.parametrize("change", ["tracked", "untracked"])
def test_package_rejects_dirty_or_untracked_tree(tmp_path, change):
    repo = init_release_repo(tmp_path)
    target = repo / ("payload.txt" if change == "tracked" else "rogue.txt")
    target.write_text("not in the release commit\n")

    completed = package(repo)

    assert completed.returncode != 0
    assert "clean" in completed.stderr.lower()
    assert_no_completed_artifacts(repo)


def test_package_rejects_absent_or_behind_tag(tmp_path):
    repo = init_release_repo(tmp_path)
    absent = package(repo, "v9.9.9")
    assert absent.returncode != 0
    assert "tag" in absent.stderr.lower()
    assert_no_completed_artifacts(repo, "v9.9.9")

    (repo / "payload.txt").write_text("new commit\n")
    git(repo, "add", "payload.txt")
    git(repo, "commit", "-q", "-m", "ahead")
    behind = package(repo)
    assert behind.returncode != 0
    assert "head" in behind.stderr.lower()
    assert_no_completed_artifacts(repo)


def test_package_rejects_missing_changelog_or_failed_verifier(tmp_path):
    repo = init_release_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n")
    git(repo, "add", "CHANGELOG.md")
    git(repo, "commit", "-q", "-m", "remove release note")
    retag_head(repo)

    missing = package(repo)
    assert missing.returncode != 0
    assert "changelog" in missing.stderr.lower()
    assert_no_completed_artifacts(repo)

    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{TAG}] - 2026-08-02\n")
    git(repo, "add", "CHANGELOG.md")
    git(repo, "commit", "-q", "-m", "restore release note")
    retag_head(repo)
    failed = package(repo, FAIL_VERIFY="1")
    assert failed.returncode != 0
    assert_no_completed_artifacts(repo)


def test_exact_tag_package_is_tracked_reproducible_and_self_consistent(tmp_path):
    repo = init_release_repo(tmp_path)

    completed = package(repo)

    assert completed.returncode == 0, completed.stderr
    installer, archive, checksums = artifacts(repo)
    assert installer.is_file() and os.access(installer, os.X_OK)
    assert archive.is_file() and checksums.is_file()

    tracked = set(git(repo, "ls-tree", "-r", "--name-only", TAG).splitlines())
    with tarfile.open(archive, "r:gz") as payload:
        assert {member.name for member in payload.getmembers() if member.isfile()} == tracked

    data = installer.read_bytes()
    match = re.search(rb"^PAYLOAD_LINE=(\d+)$", data, re.MULTILINE)
    assert match
    payload_line = int(match.group(1))
    assert data.split(b"\n", payload_line - 1)[payload_line - 1] == archive.read_bytes()
    assert re.search(rb"^VERSION=" + TAG.encode() + rb"$", data, re.MULTILINE)

    expected = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (installer, archive)
    }
    actual = {line.split()[1]: line.split()[0] for line in checksums.read_text().splitlines()}
    assert actual == expected

    assert package(repo).returncode == 0
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (installer, archive)
    } == expected


def test_artifact_verifier_rejects_unsafe_tar_member(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as payload:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        payload.addfile(member, io.BytesIO(b"x"))

    completed = run(
        [sys.executable, str(SOURCE / "scripts" / "release-verify.py"), "--archive", str(archive)],
        SOURCE,
    )

    assert completed.returncode != 0
    assert "unsafe" in completed.stderr.lower()


def test_artifact_verifier_rejects_payload_or_version_mismatch(tmp_path):
    repo = init_release_repo(tmp_path)
    assert package(repo).returncode == 0
    installer, archive, _ = artifacts(repo)
    broken = tmp_path / "broken.sh"
    broken.write_bytes(installer.read_bytes() + b"x")

    mismatch = run(
        [sys.executable, str(SOURCE / "scripts" / "release-verify.py"),
         "--archive", str(archive), "--installer", str(broken), "--tag", TAG],
        SOURCE,
    )
    wrong_version = run(
        [sys.executable, str(SOURCE / "scripts" / "release-verify.py"),
         "--archive", str(archive), "--installer", str(installer), "--tag", "v9.9.9"],
        SOURCE,
    )

    assert mismatch.returncode != 0 and "payload" in mismatch.stderr.lower()
    assert wrong_version.returncode != 0 and "version" in wrong_version.stderr.lower()


def test_release_documentation_has_truth_boundaries_and_feature_matrix():
    readme = (SOURCE / "README.md").read_text()
    compatibility = (SOURCE / "docs" / "compatibility.md").read_text()
    changelog = (SOURCE / "CHANGELOG.md").read_text()

    for term in ("Feature", "Claude Code", "Codex", "Verified", "Not verified"):
        assert term in readme
    for term in ("0.146.0", "2026-08-02", "SubagentStart", "shared filesystem",
                 "separate conversation", "explicit refresh", "gpt-5.6-luna"):
        assert term in compatibility
    assert "## [Unreleased]" in changelog
    assert "contarch-15d5dd0" in changelog
