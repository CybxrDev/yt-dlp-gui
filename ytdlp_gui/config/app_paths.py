"""
Where the app stores its own files.

Normal install (per user):
    Windows  %LOCALAPPDATA%\\yt-dlp-gui
    macOS    ~/Library/Application Support/yt-dlp-gui
    Linux    $XDG_DATA_HOME/yt-dlp-gui  (usually ~/.local/share/yt-dlp-gui)

Portable mode: if a file named "portable.txt" sits next to the executable (or next to
run.py when running from source), everything is stored in a "data" folder beside it instead.

For development/testing, the environment variable YTDLP_GUI_DATA_DIR overrides both.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ytdlp_gui import APP_ID

PORTABLE_MARKER = "portable.txt"


def app_install_dir() -> Path:
    """Folder containing the executable (compiled app) or the project root (source checkout)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _platform_data_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_ID
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_ID


@dataclass(frozen=True)
class AppPaths:
    """All file locations used by the app, derived from one root folder."""

    root: Path

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    @property
    def history_file(self) -> Path:
        return self.root / "history.json"

    @property
    def log_file(self) -> Path:
        return self.root / "app.log"

    @property
    def thumbnails_dir(self) -> Path:
        return self.root / "thumbnails"

    @property
    def tools_dir(self) -> Path:
        """Downloaded tools (FFmpeg, Deno, yt-dlp program) live in sub-folders here."""
        return self.root / "tools"

    @property
    def ytdlp_library_dir(self) -> Path:
        """Updated copy of the yt-dlp Python package (see tools/ytdlp_library_loader.py)."""
        return self.tools_dir / "yt-dlp-library"

    def ensure_exists(self) -> None:
        for folder in (self.root, self.thumbnails_dir, self.tools_dir):
            folder.mkdir(parents=True, exist_ok=True)


def resolve_app_paths() -> AppPaths:
    install_dir = app_install_dir()
    if os.environ.get("YTDLP_GUI_DATA_DIR"):
        root = Path(os.environ["YTDLP_GUI_DATA_DIR"]).expanduser()
    elif (install_dir / PORTABLE_MARKER).exists():
        root = install_dir / "data"
    else:
        root = _platform_data_root()
    paths = AppPaths(root)
    paths.ensure_exists()
    return paths


def default_download_dir() -> Path:
    """The user's Downloads folder (respecting a relocated folder on Windows)."""
    if sys.platform == "win32":
        known = _windows_downloads_folder()
        if known and known.is_dir():
            return known
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def _windows_downloads_folder() -> Path | None:
    """Ask Windows for the real Downloads folder (users can move it to another drive)."""
    try:
        import ctypes
        from ctypes import wintypes
        import uuid

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        folder_id = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")  # FOLDERID_Downloads
        guid = GUID.from_buffer_copy(folder_id.bytes_le)
        path_ptr = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr))
        if result != 0:
            return None
        path = Path(path_ptr.value)
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)
        return path
    except Exception:
        return None
