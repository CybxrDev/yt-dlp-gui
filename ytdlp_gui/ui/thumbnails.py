"""
Thumbnails shown in the Downloads and History lists.

Tk can only display PNG/GIF, but video sites serve JPEG or WebP. Instead of adding an
image library, FFmpeg (which the app needs anyway) converts each thumbnail once into a
small PNG cached at <data>/thumbnails/<video id>.png. Without FFmpeg the lists simply
show no thumbnails.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable

from ytdlp_gui.tools.http_client import download_file
from ytdlp_gui.tools.platform_info import hidden_process_kwargs
from ytdlp_gui.tools.tool_manager import ToolManager

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 80, 45  # 16:9


class ThumbnailCache:
    def __init__(self, cache_dir: Path, tools: ToolManager, call_soon: Callable[[Callable], None]):
        self._dir = cache_dir
        self._tools = tools
        self._call_soon = call_soon  # runs a function on the UI thread
        self._images: dict = {}
        self._waiting: dict = {}
        self.blank: tk.PhotoImage | None = None

    def placeholder(self) -> tk.PhotoImage:
        """An empty image of thumbnail size, so layouts don't jump when the real one arrives."""
        if self.blank is None:
            self.blank = tk.PhotoImage(width=WIDTH, height=HEIGHT)
        return self.blank

    def request(self, key: str, url: str, callback: Callable[[tk.PhotoImage], None]) -> None:
        """Call `callback(image)` on the UI thread once the thumbnail is available."""
        key = _safe_name(key)
        if not key:
            return
        if key in self._images:
            callback(self._images[key])
            return
        png = self._dir / f"{key}.png"
        if png.is_file():
            image = self._load(key, png)
            if image is not None:
                callback(image)
                return
        if not url:
            return
        if key in self._waiting:
            self._waiting[key].append(callback)
            return
        self._waiting[key] = [callback]
        threading.Thread(target=self._fetch, args=(key, url, png), daemon=True).start()

    def forget(self, key: str) -> None:
        key = _safe_name(key)
        self._images.pop(key, None)
        (self._dir / f"{key}.png").unlink(missing_ok=True)

    # --- background work -----------------------------------------------------------------

    def _fetch(self, key: str, url: str, png: Path) -> None:
        ok = False
        try:
            ffmpeg = self._tools.find_ffmpeg()
            if ffmpeg is not None:
                with tempfile.TemporaryDirectory() as tmp:
                    source = download_file(url, Path(tmp) / "thumbnail")
                    converted = Path(tmp) / "thumbnail.png"
                    scale = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                             f"crop={WIDTH}:{HEIGHT}")
                    subprocess.run(
                        [str(ffmpeg), "-y", "-loglevel", "error", "-i", str(source), "-vf", scale,
                         "-frames:v", "1", str(converted)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=30, check=True, **hidden_process_kwargs())
                    converted.replace(png)
                    ok = True
        except Exception as exc:
            log.debug("Thumbnail %s failed: %s", url, exc)
        self._call_soon(lambda: self._deliver(key, png if ok else None))

    def _deliver(self, key: str, png: Path | None) -> None:
        callbacks = self._waiting.pop(key, [])
        image = self._load(key, png) if png else None
        if image is None:
            return
        for callback in callbacks:
            try:
                callback(image)
            except tk.TclError:
                pass  # the widget was closed meanwhile

    def _load(self, key: str, png: Path) -> tk.PhotoImage | None:
        try:
            image = tk.PhotoImage(file=str(png))
        except tk.TclError:
            png.unlink(missing_ok=True)
            return None
        self._images[key] = image
        return image


def _safe_name(key: str) -> str:
    return re.sub(r"[^\w.-]", "_", key)[:120]
