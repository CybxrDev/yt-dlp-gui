"""
User settings, saved as JSON in the app data folder (see app_paths.py).

Loading is forgiving on purpose: unknown keys are ignored and missing or invalid values
fall back to the defaults below, so an old or hand-edited settings file never stops the
app from starting. To add a setting: add a field here (with its default), then expose it
in ui/settings_dialog.py.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ytdlp_gui.config.app_paths import default_download_dir
from ytdlp_gui.downloads.format_selection import FORMAT_CHOICES, RESOLUTION_CHOICES

log = logging.getLogger(__name__)

THEMES = ("system", "light", "dark")

# "library" = yt-dlp imported as a Python package (bundled with the app, updatable)
# "cli"     = run the yt-dlp program as a separate process (independent of this app)
ENGINES = ("library", "cli")

# Where an external tool comes from:
# "managed" = downloaded and updated by this app, "system" = found on PATH, "custom" = a path you choose
TOOL_SOURCES = ("managed", "system", "custom")

COOKIE_BROWSERS = ("", "brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale")

DEFAULT_FILENAME_PATTERN = "[title] - [id]"


@dataclass
class Settings:
    # --- Defaults for new downloads (the download form starts with these) ---
    download_dir: str = field(default_factory=lambda: str(default_download_dir()))
    file_format: str = "mp4"
    resolution: str = "best"
    filename_pattern: str = DEFAULT_FILENAME_PATTERN
    whole_playlist: bool = False  # for links that point at a video *inside* a playlist

    # --- What goes inside the downloaded file ---
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    embed_chapters: bool = True

    # --- Queue ---
    max_parallel_downloads: int = 2

    # --- Appearance ---
    theme: str = "system"

    # --- History ---
    history_enabled: bool = True

    # --- Engine and external tools ---
    engine: str = "library"
    ytdlp_cli_source: str = "managed"
    ytdlp_cli_path: str = ""
    ffmpeg_source: str = "managed"
    ffmpeg_path: str = ""
    js_runtime_source: str = "managed"
    js_runtime_path: str = ""
    # Let yt-dlp fetch its YouTube challenge-solver scripts from GitHub if the local copy
    # doesn't match its version (a fallback; normally not needed).
    allow_remote_components: bool = True
    # Optional: use cookies from a browser (for age-restricted videos). Empty = never.
    cookies_from_browser: str = ""

    # --- Updates ---
    check_updates_on_startup: bool = True
    last_update_check: float = 0.0

    # --- Window ---
    window_geometry: str = ""

    def validate(self) -> None:
        """Replace invalid values with defaults (in place)."""
        defaults = Settings()
        choices = {
            "file_format": FORMAT_CHOICES,
            "resolution": RESOLUTION_CHOICES,
            "theme": THEMES,
            "engine": ENGINES,
            "ytdlp_cli_source": TOOL_SOURCES,
            "ffmpeg_source": TOOL_SOURCES,
            "js_runtime_source": TOOL_SOURCES,
            "cookies_from_browser": COOKIE_BROWSERS,
        }
        for name, allowed in choices.items():
            if getattr(self, name) not in allowed:
                setattr(self, name, getattr(defaults, name))
        self.max_parallel_downloads = max(1, min(int(self.max_parallel_downloads), 5))
        if not self.filename_pattern.strip():
            self.filename_pattern = DEFAULT_FILENAME_PATTERN
        if not self.download_dir.strip():
            self.download_dir = defaults.download_dir


def load_settings(path: Path) -> Settings:
    settings = Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return settings
    except (OSError, ValueError) as exc:
        log.warning("Could not read settings (%s); using defaults", exc)
        return settings

    for f in fields(Settings):
        if f.name not in data:
            continue
        value = data[f.name]
        default = getattr(settings, f.name)
        # Only accept values of the same type as the default (int is fine for float fields).
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = type(value) is type(default)
        if ok:
            setattr(settings, f.name, value)
    settings.validate()
    return settings


def save_settings(settings: Settings, path: Path) -> None:
    """Write atomically (temp file + rename) so a crash can't leave a half-written file."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.error("Could not save settings: %s", exc)
