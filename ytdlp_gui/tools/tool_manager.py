"""
WHICH copy of each external tool is used, what version it is, and installing/updating it.

Every tool (except the built-in library) has a "source" chosen in Settings → Engine & tools:
    managed  downloaded and kept up to date by this app (in <data>/tools/<tool>/)
    system   found on PATH (installed with a package manager, Homebrew, etc.)
    custom   an executable file the user picked

Version lookups run external programs and install/update use the network, so call those
from a background thread (the UI does this through App.run_in_background).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tarfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from ytdlp_gui.config.app_paths import AppPaths
from ytdlp_gui.config.settings import Settings
from ytdlp_gui.tools import tool_sources, ytdlp_library_loader
from ytdlp_gui.tools.http_client import download_file
from ytdlp_gui.tools.platform_info import exe_name, find_on_path, make_executable, run_quietly

log = logging.getLogger(__name__)

YTDLP_LIBRARY = "ytdlp_library"
YTDLP_PROGRAM = "ytdlp_program"
FFMPEG = "ffmpeg"
DENO = "deno"  # the JavaScript runtime slot (Deno when managed; may be node/bun if system/custom)

# progress(message, fraction 0..1 or None when unknown)
InstallProgress = Callable[[str, "float | None"], None]


@dataclass(frozen=True)
class ToolInfo:
    key: str
    name: str
    purpose: str


TOOLS = (
    ToolInfo(YTDLP_LIBRARY, "yt-dlp (built-in library)", "Downloads media (default engine)"),
    ToolInfo(YTDLP_PROGRAM, "yt-dlp (program)", "Downloads media (alternative engine)"),
    ToolInfo(FFMPEG, "FFmpeg", "Merges video + audio, converts, embeds thumbnails"),
    ToolInfo(DENO, "Deno (JavaScript)", "Solves YouTube's player challenges"),
)
TOOL_NAMES = {t.key: t.name for t in TOOLS}

# JavaScript runtimes yt-dlp supports, by executable name.
_JS_RUNTIME_NAMES = {"deno": "deno", "node": "node", "nodejs": "node", "bun": "bun", "qjs": "quickjs", "quickjs": "quickjs"}

_MANAGED_FOLDERS = {YTDLP_PROGRAM: "yt-dlp", FFMPEG: "ffmpeg", DENO: "deno"}
_MANAGED_EXECUTABLES = {YTDLP_PROGRAM: "yt-dlp", FFMPEG: "ffmpeg", DENO: "deno"}
_SOURCE_LABELS = {"managed": "Downloaded by app", "system": "System (PATH)", "custom": "Custom path"}


class ToolError(Exception):
    """A problem installing or using a tool, with a message meant for the user."""


@dataclass(frozen=True)
class ResolvedTools:
    """The tool copies a download will use (None = not available)."""

    ffmpeg_dir: Path | None
    js_runtime: tuple | None  # (runtime name for yt-dlp, executable path)
    ytdlp_program: Path | None


@dataclass
class ToolStatus:
    key: str
    source_label: str
    installed_version: str | None
    location: str = ""
    can_update: bool = False  # True when this app manages the tool
    note: str = ""


class ToolManager:
    def __init__(self, paths: AppPaths, get_settings: Callable[[], Settings]):
        self._paths = paths
        self._settings = get_settings
        self._manifest_file = paths.tools_dir / "manifest.json"
        self._version_cache: dict = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------------------------
    # Locating tools
    # ----------------------------------------------------------------------------------

    def managed_executable(self, key: str) -> Path:
        return self._paths.tools_dir / _MANAGED_FOLDERS[key] / exe_name(_MANAGED_EXECUTABLES[key])

    def source_of(self, key: str) -> str:
        s = self._settings()
        return {YTDLP_PROGRAM: s.ytdlp_cli_source, FFMPEG: s.ffmpeg_source, DENO: s.js_runtime_source}.get(key, "managed")

    def _locate(self, key: str, system_names: tuple) -> Path | None:
        s = self._settings()
        source = self.source_of(key)
        if source == "managed":
            path = self.managed_executable(key)
            return path if path.is_file() else None
        if source == "custom":
            custom = {YTDLP_PROGRAM: s.ytdlp_cli_path, FFMPEG: s.ffmpeg_path, DENO: s.js_runtime_path}[key]
            path = Path(custom).expanduser() if custom else None
            return path if path and path.is_file() else None
        for name in system_names:
            found = find_on_path(name)
            if found:
                return found
        return None

    def find_ffmpeg(self) -> Path | None:
        return self._locate(FFMPEG, ("ffmpeg",))

    def find_ytdlp_program(self) -> Path | None:
        return self._locate(YTDLP_PROGRAM, ("yt-dlp",))

    def find_js_runtime(self) -> tuple | None:
        """(yt-dlp runtime name, path) of the JavaScript runtime to use."""
        path = self._locate(DENO, ("deno", "node", "bun"))
        if path is None:
            return None
        name = _JS_RUNTIME_NAMES.get(path.stem.lower().split("-")[0], "deno")
        return name, path

    def resolve(self) -> ResolvedTools:
        ffmpeg = self.find_ffmpeg()
        return ResolvedTools(
            ffmpeg_dir=ffmpeg.parent if ffmpeg else None,
            js_runtime=self.find_js_runtime(),
            ytdlp_program=self.find_ytdlp_program(),
        )

    def missing_required(self) -> list:
        """Keys of tools the current settings need but that aren't available."""
        missing = []
        engine = self._settings().engine
        if engine == "library" and not ytdlp_library_loader.is_available():
            missing.append(YTDLP_LIBRARY)
        if engine == "cli" and self.find_ytdlp_program() is None:
            missing.append(YTDLP_PROGRAM)
        if self.find_ffmpeg() is None:
            missing.append(FFMPEG)
        if self.find_js_runtime() is None:
            missing.append(DENO)
        return missing

    # ----------------------------------------------------------------------------------
    # Versions (slow: may run programs)
    # ----------------------------------------------------------------------------------

    def status(self, key: str) -> ToolStatus:
        if key == YTDLP_LIBRARY:
            return self._library_status()
        source = self.source_of(key)
        if key == DENO:
            runtime = self.find_js_runtime()
            path = runtime[1] if runtime else None
        else:
            path = self.find_ffmpeg() if key == FFMPEG else self.find_ytdlp_program()
        label = _SOURCE_LABELS[source]
        if key == DENO and path is not None and source != "managed":
            label += f" – {path.stem}"
        version = None
        if path is not None:
            version = self._manifest().get(key, {}).get("version") if source == "managed" else None
            version = version or self._program_version(key, path)
        return ToolStatus(key, label, version, str(path or ""), can_update=source == "managed")

    def _library_status(self) -> ToolStatus:
        version = ytdlp_library_loader.current_version()
        on_disk = ytdlp_library_loader.downloaded_version()
        note = ytdlp_library_loader.fallback_reason()
        if on_disk and version and on_disk != version and not note:
            note = f"Version {on_disk} is downloaded – restart the app to use it."
        label = "Updated copy" if ytdlp_library_loader.using_updated_copy() else "Built into app"
        return ToolStatus(YTDLP_LIBRARY, label, version, str(self._paths.ytdlp_library_dir),
                          can_update=True, note=note)

    def _program_version(self, key: str, path: Path) -> str | None:
        try:
            cache_key = (str(path), path.stat().st_mtime)
        except OSError:
            return None
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]
        flag = "-version" if key == FFMPEG else "--version"
        output = run_quietly([str(path), flag], timeout=60).strip()
        version = _parse_version(path.stem.lower(), output)
        self._version_cache[cache_key] = version
        return version

    def latest_version(self, key: str) -> str:
        """Newest available version (network)."""
        if key == YTDLP_LIBRARY:
            return tool_sources.ytdlp_library_release().version
        return self._release(key).version

    @staticmethod
    def is_newer(key: str, latest: str | None, installed: str | None) -> bool:
        if not latest or not installed:
            return False
        if key == FFMPEG:  # build identifiers: any difference means a newer build
            return latest != installed
        return _version_tuple(latest) > _version_tuple(installed)

    # ----------------------------------------------------------------------------------
    # Installing / updating (network)
    # ----------------------------------------------------------------------------------

    def install(self, key: str, progress: InstallProgress, cancel: threading.Event) -> str:
        """Download and install the newest version of a tool. Returns the installed version."""
        with self._lock:
            if key == YTDLP_LIBRARY:
                return self._install_library(progress, cancel)
            return self._install_program(key, progress, cancel)

    def _release(self, key: str) -> tool_sources.Release:
        return {
            YTDLP_PROGRAM: tool_sources.ytdlp_program_release,
            FFMPEG: tool_sources.ffmpeg_release,
            DENO: tool_sources.deno_release,
        }[key]()

    def _install_program(self, key: str, progress: InstallProgress, cancel: threading.Event) -> str:
        name = TOOL_NAMES[key]
        progress(f"Looking up the latest {name}…", None)
        release = self._release(key)
        staging = self._paths.tools_dir / f".staging-{key}"
        shutil.rmtree(staging, ignore_errors=True)
        unpacked = staging / "unpacked"
        unpacked.mkdir(parents=True)
        try:
            count = len(release.artifacts)
            for number, artifact in enumerate(release.artifacts, 1):
                label = f"Downloading {name} {release.version}" + (f" ({number}/{count})" if count > 1 else "")
                archive = staging / f"download-{number}"
                download_file(artifact.url, archive, _byte_progress(progress, label), cancel)
                progress(f"Unpacking {name}…", None)
                _unpack(artifact, archive, unpacked)

            target_dir = self.managed_executable(key).parent
            target_dir.mkdir(parents=True, exist_ok=True)
            for item in unpacked.iterdir():
                make_executable(item)
                try:
                    os.replace(item, target_dir / item.name)
                except PermissionError as exc:
                    raise ToolError(f"{name} is in use. Wait for downloads to finish, then try again.") from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        self._write_manifest(key, release.version)
        self._version_cache.clear()
        log.info("Installed %s %s", name, release.version)
        return release.version

    def _install_library(self, progress: InstallProgress, cancel: threading.Event) -> str:
        progress("Looking up the latest yt-dlp…", None)
        release = tool_sources.ytdlp_library_release()
        if not _python_satisfies(release.requires_python):
            raise ToolError(
                f"yt-dlp {release.version} needs Python {release.requires_python}, but this app was built with "
                f"Python {sys.version_info.major}.{sys.version_info.minor}. Use the 'command-line program' engine "
                "(Settings → Engine & tools) or a newer version of this app.")

        target = self._paths.ytdlp_library_dir
        staging = target.with_name(target.name + ".new")
        old = target.with_name(target.name + ".old")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            for number, url in enumerate(release.wheel_urls, 1):
                wheel = staging / url.rsplit("/", 1)[-1]
                label = f"Downloading yt-dlp {release.version} ({number}/{len(release.wheel_urls)})"
                download_file(url, wheel, _byte_progress(progress, label), cancel)
                with zipfile.ZipFile(wheel) as archive:
                    archive.extractall(staging)  # zipfile strips absolute paths and ".."
                wheel.unlink()
            if not (staging / "yt_dlp" / "__init__.py").is_file():
                raise ToolError("The downloaded yt-dlp package looks incomplete.")
            shutil.rmtree(old, ignore_errors=True)
            if target.exists():
                target.rename(old)
            staging.rename(target)
            shutil.rmtree(old, ignore_errors=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        log.info("Downloaded yt-dlp library %s (active after restart)", release.version)
        return release.version

    def remove_library_update(self) -> None:
        """Go back to the yt-dlp copy built into the app (takes effect after restart)."""
        shutil.rmtree(self._paths.ytdlp_library_dir, ignore_errors=True)

    # ----------------------------------------------------------------------------------
    # Manifest: remembers which version of each managed tool was installed
    # ----------------------------------------------------------------------------------

    def _manifest(self) -> dict:
        try:
            data = json.loads(self._manifest_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_manifest(self, key: str, version: str) -> None:
        data = self._manifest()
        data[key] = {"version": version, "installed_at": time.time()}
        self._manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _byte_progress(progress: InstallProgress, label: str):
    def report(done: int, total: int | None) -> None:
        size = f"{done / 1_048_576:.1f}" + (f" / {total / 1_048_576:.1f} MB" if total else " MB")
        progress(f"{label}  {size}", done / total if total else None)
    return report


def _unpack(artifact: tool_sources.Artifact, archive: Path, out_dir: Path) -> None:
    """Copy only the wanted executables out of the download (never arbitrary paths)."""
    wanted = dict(artifact.files)
    if artifact.archive == "file":
        (installed_name,) = wanted.values()
        shutil.copyfile(archive, out_dir / installed_name)
        return
    found = set()
    if artifact.archive == "zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                base = PurePosixPath(info.filename).name
                if not info.is_dir() and base in wanted:
                    with zf.open(info) as src, open(out_dir / wanted[base], "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.add(base)
    elif artifact.archive == "tar.xz":
        with tarfile.open(archive, "r:xz") as tf:
            for member in tf.getmembers():
                base = PurePosixPath(member.name).name
                if member.isfile() and base in wanted:
                    src = tf.extractfile(member)
                    with src, open(out_dir / wanted[base], "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.add(base)
    missing = set(wanted) - found
    if missing:
        raise ToolError(f"The download did not contain: {', '.join(sorted(missing))}")


def _parse_version(program: str, output: str) -> str | None:
    """Pull a version out of `--version` / `-version` output."""
    first_line = output.splitlines()[0].strip() if output.strip() else ""
    if not first_line:
        return None
    words = first_line.split()
    if program.startswith("ffmpeg") and len(words) >= 3 and words[1] == "version":
        return words[2]
    if program.startswith("deno") and len(words) >= 2:
        return words[1]
    return words[0].lstrip("v")  # yt-dlp prints just the version; node prints "v22.1.0"


def _version_tuple(version: str) -> tuple:
    parts = []
    for piece in version.replace("-", ".").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _python_satisfies(requires_python: str) -> bool:
    """Checks the '>=' parts of a requires-python string like '>=3.10'."""
    for clause in requires_python.split(","):
        clause = clause.strip()
        if clause.startswith(">="):
            needed = _version_tuple(clause[2:])
            if sys.version_info[: len(needed)] < needed:
                return False
    return True
