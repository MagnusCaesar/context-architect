#!/usr/bin/env python3
"""Release gates and post-build archive verification."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOC_TERMS = {
    "README.md": ("Feature", "Claude Code", "Codex", "Verified", "Not verified"),
    "CHANGELOG.md": ("## [Unreleased]", "contarch-15d5dd0"),
    "docs/compatibility.md": (
        "0.146.0", "2026-08-02", "SubagentStart", "shared filesystem",
        "separate conversation", "explicit refresh", "gpt-5.6-luna",
    ),
}


class VerificationError(RuntimeError):
    pass


def run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True,
                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def verify_docs() -> None:
    for name, terms in REQUIRED_DOC_TERMS.items():
        path = ROOT / name
        if not path.is_file():
            raise VerificationError(f"missing documentation: {name}")
        text = path.read_text()
        missing = [term for term in terms if term not in text]
        if missing:
            raise VerificationError(f"{name} missing: {', '.join(missing)}")
    contracts = (ROOT / "docs/contracts.md").read_text()
    if "compatibility.md" not in contracts:
        raise VerificationError("docs/contracts.md must link to Codex compatibility facts")


def safe_members(archive: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as payload:
            members = payload.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise VerificationError(f"invalid archive: {exc}") from exc
    if not members:
        raise VerificationError("archive is empty")
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or member.isdev():
            raise VerificationError(f"unsafe archive member: {member.name}")


def verify_installer(archive: Path, installer: Path, tag: str) -> None:
    data = installer.read_bytes()
    line = re.search(rb"^PAYLOAD_LINE=(\d+)$", data, re.MULTILINE)
    version = re.search(rb"^VERSION=([^\r\n]+)$", data, re.MULTILINE)
    if not line:
        raise VerificationError("installer payload line metadata is missing")
    if not version or version.group(1).decode(errors="replace") != tag:
        raise VerificationError(f"installer version metadata does not equal {tag}")
    payload_line = int(line.group(1))
    parts = data.split(b"\n", payload_line - 1)
    if len(parts) != payload_line or parts[-1] != archive.read_bytes():
        raise VerificationError("installer payload does not match standalone archive")


def verify_repository() -> None:
    verify_docs()
    run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    run(["bash", "smoke.sh"])
    for test in sorted((ROOT / "tests").glob("test_*.sh")):
        run(["bash", str(test.relative_to(ROOT))])
    for script in sorted((ROOT / "scripts").glob("*.py")):
        compile(script.read_bytes(), str(script.relative_to(ROOT)), "exec")
    for script in sorted({ROOT / "package.sh", ROOT / "installer-header.sh", ROOT / "smoke.sh", *(ROOT / "hooks").glob("*"), *(ROOT / "tests").glob("*.sh")}):
        if script.is_file() and (script.suffix == ".sh" or script.parent.name == "hooks"):
            run(["bash", "-n", str(script.relative_to(ROOT))])
    run(["git", "diff", "--check"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--tag")
    args = parser.parse_args()
    try:
        if args.archive:
            safe_members(args.archive)
            if bool(args.installer) != bool(args.tag):
                raise VerificationError("--installer and --tag must be provided together")
            if args.installer:
                verify_installer(args.archive, args.installer, args.tag)
        elif args.installer or args.tag:
            raise VerificationError("--archive is required with installer metadata")
        else:
            verify_repository()
    except (OSError, SyntaxError, subprocess.CalledProcessError, VerificationError) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    print("release verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
