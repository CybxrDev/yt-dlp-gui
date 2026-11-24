"""
WHERE each external tool is downloaded from, for every supported OS / CPU.

If a project moves its downloads, this is the only file that needs editing.

    yt-dlp program  official GitHub releases            github.com/yt-dlp/yt-dlp
    yt-dlp library  PyPI wheels (+ matching yt-dlp-ejs)  pypi.org/project/yt-dlp
    Deno            official GitHub releases            github.com/denoland/deno
    FFmpeg          Windows/Linux: builds recommended by yt-dlp   github.com/yt-dlp/FFmpeg-Builds
                    macOS (Intel + Apple Silicon): Martin Riedl's builds  ffmpeg.martin-riedl.de

Each `*_release()` function contacts the network and returns the newest version plus the
files to download.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ytdlp_gui.tools.http_client import get_json, redirect_target
from ytdlp_gui.tools.platform_info import cpu_arch, exe_name, os_name

GITHUB = "https://github.com"


class SourceUnavailable(Exception):
    """There is no download of this tool for the current OS / CPU."""


@dataclass(frozen=True)
class Artifact:
    url: str
    archive: str  # "zip", "tar.xz" or "file" (the download itself is the executable)
    files: dict  # file name inside the archive -> file name to install as


@dataclass(frozen=True)
class Release:
    version: str  # version or build identifier, compared with the installed one
    artifacts: tuple = ()
    page_url: str = ""


@dataclass(frozen=True)
class LibraryRelease:
    version: str
    wheel_urls: tuple  # yt-dlp wheel + the yt-dlp-ejs wheel it pins
    requires_python: str  # e.g. ">=3.10"


def _platform() -> tuple[str, str]:
    return os_name(), cpu_arch()


def _github_latest_tag(repo: str) -> str:
    """Tag of the latest release, read from the redirect of /releases/latest (no API limits)."""
    target = redirect_target(f"{GITHUB}/{repo}/releases/latest")
    if "/releases/tag/" not in target:
        raise RuntimeError(f"Unexpected GitHub response for {repo}: {target}")
    return target.rsplit("/releases/tag/", 1)[1].strip("/")


# --------------------------------------------------------------------------------------
# yt-dlp program (used by the "command-line program" engine)
# --------------------------------------------------------------------------------------

_YTDLP_ASSETS = {
    ("windows", "x86_64"): "yt-dlp.exe",
    ("windows", "x86"): "yt-dlp_x86.exe",
    ("windows", "arm64"): "yt-dlp_arm64.exe",
    ("macos", "x86_64"): "yt-dlp_macos",
    ("macos", "arm64"): "yt-dlp_macos",
    ("linux", "x86_64"): "yt-dlp_linux",
    ("linux", "arm64"): "yt-dlp_linux_aarch64",
    ("linux", "armv7"): "yt-dlp_linux_armv7l",
}


def ytdlp_program_release() -> Release:
    asset = _YTDLP_ASSETS.get(_platform())
    if not asset:
        raise SourceUnavailable("No yt-dlp program is published for this system.")
    tag = _github_latest_tag("yt-dlp/yt-dlp")
    url = f"{GITHUB}/yt-dlp/yt-dlp/releases/download/{tag}/{asset}"
    return Release(tag, (Artifact(url, "file", {asset: exe_name("yt-dlp")}),),
                   f"{GITHUB}/yt-dlp/yt-dlp/releases/tag/{tag}")


# --------------------------------------------------------------------------------------
# yt-dlp Python library (the default engine; updates are unpacked next to the app)
# --------------------------------------------------------------------------------------

def ytdlp_library_release() -> LibraryRelease:
    data = get_json("https://pypi.org/pypi/yt-dlp/json")
    info = data["info"]
    wheels = [_pure_python_wheel(data)]
    # yt-dlp pins the exact yt-dlp-ejs (YouTube challenge solver scripts) it works with.
    ejs_version = _pinned_version(info.get("requires_dist") or [], "yt-dlp-ejs")
    if ejs_version:
        wheels.append(_pure_python_wheel(get_json(f"https://pypi.org/pypi/yt-dlp-ejs/{ejs_version}/json")))
    return LibraryRelease(info["version"], tuple(wheels), info.get("requires_python") or "")


def _pure_python_wheel(pypi_data: dict) -> str:
    for item in pypi_data.get("urls", []):
        if item.get("packagetype") == "bdist_wheel" and item["filename"].endswith("-none-any.whl"):
            return item["url"]
    raise RuntimeError(f"No wheel found for {pypi_data.get('info', {}).get('name')}")


def _pinned_version(requirements: list, name: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(name)}\s*==\s*([0-9][\w.]*)", re.IGNORECASE)
    for requirement in requirements:
        match = pattern.match(requirement.strip())
        if match:
            return match.group(1)
    return None


# --------------------------------------------------------------------------------------
# Deno (JavaScript runtime yt-dlp uses for YouTube)
# --------------------------------------------------------------------------------------

_DENO_TARGETS = {
    ("windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("windows", "arm64"): "aarch64-pc-windows-msvc",
    ("macos", "x86_64"): "x86_64-apple-darwin",
    ("macos", "arm64"): "aarch64-apple-darwin",
    ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
}


def deno_release() -> Release:
    target = _DENO_TARGETS.get(_platform())
    if not target:
        raise SourceUnavailable("Deno is not published for this system; choose another JavaScript runtime in Settings.")
    tag = _github_latest_tag("denoland/deno")
    url = f"{GITHUB}/denoland/deno/releases/download/{tag}/deno-{target}.zip"
    deno = exe_name("deno")
    return Release(tag.lstrip("v"), (Artifact(url, "zip", {deno: deno}),),
                   f"{GITHUB}/denoland/deno/releases/tag/{tag}")


# --------------------------------------------------------------------------------------
# FFmpeg (+ ffprobe)
# --------------------------------------------------------------------------------------

_FFMPEG_BUILDS = {
    ("windows", "x86_64"): "ffmpeg-master-latest-win64-gpl.zip",
    ("windows", "arm64"): "ffmpeg-master-latest-winarm64-gpl.zip",
    ("windows", "x86"): "ffmpeg-master-latest-win32-gpl.zip",
    ("linux", "x86_64"): "ffmpeg-master-latest-linux64-gpl.tar.xz",
    ("linux", "arm64"): "ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
}
_FFMPEG_REPO = "yt-dlp/FFmpeg-Builds"


def ffmpeg_release() -> Release:
    if os_name() == "macos":
        return _ffmpeg_macos_release()
    asset = _FFMPEG_BUILDS.get(_platform())
    if not asset:
        raise SourceUnavailable("No FFmpeg build is available for this system; install FFmpeg yourself "
                                "and choose 'System' in Settings.")
    files = {exe_name("ffmpeg"): exe_name("ffmpeg"), exe_name("ffprobe"): exe_name("ffprobe")}
    archive = "zip" if asset.endswith(".zip") else "tar.xz"
    page = f"{GITHUB}/{_FFMPEG_REPO}/releases/tag/latest"
    # The "latest" tag is rebuilt daily; the asset's upload date identifies the build.
    data = get_json(f"https://api.github.com/repos/{_FFMPEG_REPO}/releases/tags/latest")
    for item in data.get("assets", []):
        if item.get("name") == asset:
            version = "build " + item.get("updated_at", "")[:10]
            return Release(version, (Artifact(item["browser_download_url"], archive, files),), page)
    raise RuntimeError(f"{asset} not found in {_FFMPEG_REPO}")


def _ffmpeg_macos_release() -> Release:
    arch = "arm64" if cpu_arch() == "arm64" else "amd64"
    # Redirects to e.g. https://ffmpeg.martin-riedl.de/download/macos/arm64/1795207104_9.1/ffmpeg.zip
    target = redirect_target(f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/ffmpeg.zip")
    folder = target.rsplit("/", 1)[0]
    build = folder.rsplit("/", 1)[1]
    stamp, _, number = build.partition("_")
    version = f"{number} (build {stamp})" if number else build
    return Release(version, (
        Artifact(f"{folder}/ffmpeg.zip", "zip", {"ffmpeg": "ffmpeg"}),
        Artifact(f"{folder}/ffprobe.zip", "zip", {"ffprobe": "ffprobe"}),
    ), "https://ffmpeg.martin-riedl.de/")


# --------------------------------------------------------------------------------------
# This app (optional, see APP_UPDATE_REPO in ytdlp_gui/__init__.py)
# --------------------------------------------------------------------------------------

def app_release(repo: str) -> Release:
    tag = _github_latest_tag(repo)
    return Release(tag.lstrip("v"), (), f"{GITHUB}/{repo}/releases/tag/{tag}")
