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
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Release Test")
    git(repo, "config", "user.email", "release@example.invalid")
    (repo / ".gitignore").write_text("dist/\n")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SOURCE / "package.sh", repo / "package.sh")
    shutil.copy2(SOURCE / "installer-header.sh", repo / "installer-header.sh")
    verifier = SOURCE / "scripts" / "release-verify.sh"
    if verifier.exists():
        shutil.copy2(verifier, repo / "scripts" / "release-verify.sh")
    else:
        (repo / "scripts" / "release-verify.sh").write_text("#!/usr/bin/env bash\nexec python3 scripts/release-verify.py \"$@\"\n")
        (repo / "scripts" / "release-verify.sh").chmod(0o755)
    (repo / "scripts" / "release-verify.py").write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, subprocess, sys\n"
        "marker = os.environ.get('VERIFY_MARKER')\n"
        "if marker: pathlib.Path(marker).write_text('called')\n"
        "if os.environ.get('MUTATE_HEAD'):\n"
        "    pathlib.Path('payload.txt').write_text('verifier mutation\\n')\n"
        "    subprocess.run(['git', 'add', 'payload.txt'], check=True)\n"
        "    subprocess.run(['git', 'commit', '-q', '-m', 'verifier mutation'], check=True)\n"
        "if os.environ.get('MOVE_TAG'):\n"
        f"    subprocess.run(['git', 'tag', '-f', '{TAG}', 'HEAD^'], check=True, stdout=subprocess.DEVNULL)\n"
        "raise SystemExit(17 if os.environ.get('FAIL_VERIFY') else 0)\n"
    )
    (repo / "README.md").write_text("# fixture\n")
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{TAG}] - 2026-08-02\n\n- Fixture.\n")
    (repo / "payload.txt").write_text("tracked payload\n")
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
    stem = repo / "dist" / f"contarch-{tag}" / f"contarch-{tag}"
    return Path(f"{stem}.sh"), Path(f"{stem}.tar.gz"), Path(f"{stem}.sha256")


def assert_no_completed_artifacts(repo, tag=TAG):
    assert not (repo / "dist" / f"contarch-{tag}").exists()


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

    shutil.rmtree(installer.parent)
    assert package(repo).returncode == 0
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (installer, archive)
    } == expected


@pytest.mark.parametrize("mutation, message", [
    ({"MUTATE_HEAD": "1"}, "head"),
    ({"MOVE_TAG": "1"}, "tag"),
])
def test_verifier_cannot_race_pinned_head_or_tag(tmp_path, mutation, message):
    repo = init_release_repo(tmp_path)
    pinned = git(repo, "rev-parse", "HEAD")

    completed = package(repo, **mutation)

    assert completed.returncode != 0
    assert message in completed.stderr.lower()
    assert_no_completed_artifacts(repo)
    assert pinned != git(repo, "rev-parse", "HEAD") or mutation.get("MOVE_TAG")


def test_preexisting_release_directory_fails_before_verifier_without_clobber(tmp_path):
    repo = init_release_repo(tmp_path)
    destination = repo / "dist" / f"contarch-{TAG}"
    destination.mkdir(parents=True)
    sentinel = destination / "sentinel"
    sentinel.write_bytes(b"old release")
    marker = tmp_path / "verifier-called"

    completed = package(repo, VERIFY_MARKER=str(marker))

    assert completed.returncode != 0
    assert "exists" in completed.stderr.lower()
    assert sentinel.read_bytes() == b"old release"
    assert not marker.exists()


@pytest.mark.parametrize("collision", [False, True])
def test_publication_failure_never_leaves_a_partial_release(tmp_path, collision):
    repo = init_release_repo(tmp_path)
    destination = repo / "dist" / f"contarch-{TAG}"
    wrappers = tmp_path / "bin"
    wrappers.mkdir()
    real_mv = shutil.which("mv")
    wrapper = wrappers / "mv"
    if collision:
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            "dest=${@: -1}\n"
            "mkdir -p \"$dest\"\n"
            "printf old > \"$dest/sentinel\"\n"
            f"exec {real_mv} \"$@\"\n"
        )
    else:
        wrapper.write_text("#!/usr/bin/env bash\nexit 23\n")
    wrapper.chmod(0o755)

    completed = package(repo, PATH=f"{wrappers}:{os.environ['PATH']}")

    assert completed.returncode != 0
    if collision:
        assert (destination / "sentinel").read_bytes() == b"old"
        assert not any(path.name.startswith("contarch-") for path in destination.iterdir())
    else:
        assert not destination.exists()


def test_canonical_shell_verifier_is_executable_and_package_uses_it():
    verifier = SOURCE / "scripts" / "release-verify.sh"
    assert verifier.is_file() and os.access(verifier, os.X_OK)
    assert "release-verify.sh" in (SOURCE / "package.sh").read_text()
    assert "release-verify.py" in verifier.read_text()


def test_artifact_verifier_rejects_unsafe_tar_member(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as payload:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        payload.addfile(member, io.BytesIO(b"x"))

    completed = run(
        ["bash", str(SOURCE / "scripts" / "release-verify.sh"), "--archive", str(archive)],
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
    compatibility = (SOURCE / "docs" / "codex-compatibility.md").read_text()
    summary = (SOURCE / "docs" / "compatibility.md").read_text()
    contracts = (SOURCE / "docs" / "contracts.md").read_text()
    changelog = (SOURCE / "CHANGELOG.md").read_text()

    for term in ("Feature", "Claude Code", "Codex", "Verified", "Not verified"):
        assert term in readme
    for term in ("0.146.0", "2026-08-02", "SubagentStart", "shared filesystem",
                 "separate conversation", "explicit refresh", "gpt-5.6-luna"):
        assert term in compatibility
    assert "## [Unreleased]" in changelog
    assert "contarch-15d5dd0" in changelog
    assert "codex-compatibility.md" in summary
    for gate in ("exact tag", "clean", "HEAD", "git archive", "transactional"):
        assert gate in contracts
