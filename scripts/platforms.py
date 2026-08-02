"""Small Claude/Codex instruction adapters."""

import os
import tempfile
from pathlib import Path


PLATFORMS = ("claude", "codex")
BOOTLOADER_START = "<!-- context-architecture:start -->"
BOOTLOADER_END = "<!-- context-architecture:end -->"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


class PlatformError(ValueError):
    pass


def _present(value) -> bool:
    return value.is_dir() if isinstance(value, Path) else bool(value)


def resolve_platform(explicit, env, homes) -> tuple[str, ...]:
    """Resolve an explicit or unambiguous Claude/Codex selection."""
    if explicit:
        if explicit == "both":
            return PLATFORMS
        if explicit in PLATFORMS:
            return (explicit,)
        raise PlatformError("choose --platform claude|codex|both")

    detected = tuple(
        platform for platform, variable in (("claude", "CLAUDE_CODE"), ("codex", "CODEX"))
        if env.get(variable)
    )
    if not detected:
        detected = tuple(platform for platform in PLATFORMS if _present(homes.get(platform)))
    if len(detected) == 1:
        return detected
    if len(detected) > 1:
        raise PlatformError("both Claude and Codex are available; choose --platform claude|codex|both")
    raise PlatformError("could not detect Claude or Codex; choose --platform claude|codex|both")


def platform_homes(home=None) -> dict[str, Path]:
    home = Path.home() if home is None else Path(home)
    return {platform: home / f".{platform}" for platform in PLATFORMS}


def platform_choice(platforms) -> str:
    platforms = tuple(platforms)
    if platforms == PLATFORMS:
        return "both"
    if len(platforms) == 1 and platforms[0] in PLATFORMS:
        return platforms[0]
    raise PlatformError("stored platform must be claude, codex, or both")


def render_bootloader(platform: str) -> str:
    if platform not in PLATFORMS:
        raise PlatformError("platform must be claude or codex")
    block = ((TEMPLATES / "bootloader-core.md").read_text() + (TEMPLATES / f"bootloader-{platform}.md").read_text()).rstrip("\n")
    _marker_span(block.encode())
    return block


def _marker_span(data: bytes) -> tuple[int, int]:
    start = BOOTLOADER_START.encode()
    end = BOOTLOADER_END.encode()
    if data.count(start) != 1 or data.count(end) != 1:
        raise PlatformError("managed markers must appear exactly once")
    left = data.index(start)
    right = data.index(end)
    if right < left:
        raise PlatformError("managed markers are malformed")
    return left, right + len(end)


def _write_if_changed(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        staged = Path(handle.name)
    os.replace(staged, path)


def upsert_bootloader(path: Path, platform: str, title: str) -> None:
    block = render_bootloader(platform).encode()
    _marker_span(block)
    if not path.exists():
        _write_if_changed(path, f"# {title}\n\n".encode() + block + b"\n")
        return
    authored = path.read_bytes()
    starts = authored.count(BOOTLOADER_START.encode())
    ends = authored.count(BOOTLOADER_END.encode())
    if starts == 0 and ends == 0:
        separator = b"" if not authored else b"\n\n"
        _write_if_changed(path, authored + separator + block + b"\n")
        return
    left, right = _marker_span(authored)
    _write_if_changed(path, authored[:left] + block + authored[right:])


def install_bootloaders(target: Path, platforms) -> list[str]:
    files = {"claude": ("CLAUDE.md", "Claude Instructions"), "codex": ("AGENTS.md", "Agent Instructions")}
    written = []
    for platform in tuple(platforms):
        filename, title = files[platform]
        upsert_bootloader(target / filename, platform, title)
        written.append(filename)
    return written
