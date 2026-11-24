"""
Application start-up and the glue between the parts.

`App` owns the shared objects (settings, history, tools, download queue, theme) and is
passed to the UI classes, which reach everything through it. It also provides the only
bridge from background threads to the UI:

    app.call_soon(fn)                    run fn on the UI thread (safe from any thread)
    app.run_in_background(work, done)    run work() on a thread, then done(result) on the UI thread

Start-up order matters: the yt-dlp import hook must be installed before anything imports
yt_dlp (see tools/ytdlp_library_loader.py).
"""

from __future__ import annotations

import base64
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from logging.handlers import RotatingFileHandler
from tkinter import messagebox
from typing import Callable

from ytdlp_gui import APP_NAME, APP_VERSION
from ytdlp_gui.config.app_paths import resolve_app_paths
from ytdlp_gui.config.history import HistoryEntry, HistoryStore
from ytdlp_gui.config.settings import load_settings, save_settings
from ytdlp_gui.downloads.download_queue import DownloadQueue, FileDownloaded, JobChanged, JobFinished
from ytdlp_gui.downloads.models import DownloadRequest, JobState
from ytdlp_gui.tools import ytdlp_library_loader
from ytdlp_gui.tools.tool_manager import DENO, FFMPEG, TOOL_NAMES, TOOLS, YTDLP_LIBRARY, ToolManager

log = logging.getLogger(__name__)

UPDATE_CHECK_INTERVAL = 24 * 3600  # seconds between automatic update checks


class App:
    def __init__(self) -> None:
        self.paths = resolve_app_paths()
        _setup_logging(self.paths.log_file)
        log.info("Starting %s %s (Python %s, %s)", APP_NAME, APP_VERSION, sys.version.split()[0], sys.platform)

        self.settings = load_settings(self.paths.settings_file)
        ytdlp_library_loader.activate(self.paths.ytdlp_library_dir)  # before anything imports yt_dlp
        self.history = HistoryStore(self.paths.history_file)
        self.tools = ToolManager(self.paths, lambda: self.settings)
        self._ui_calls: queue.Queue = queue.Queue()
        self.queue = DownloadQueue(lambda: self.settings, self.tools,
                                   lambda note: self.call_soon(lambda: self._on_download_notification(note)))
        self._updates: list = []
        self._tools_dialog = None

        _enable_windows_dpi_awareness()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.minsize(760, 560)
        self.root.report_callback_exception = self._on_ui_exception
        self._set_icon()

        # UI modules are imported here so the rest of the app works without a display.
        from ytdlp_gui.ui.main_window import MainWindow
        from ytdlp_gui.ui.theme import ThemeManager
        from ytdlp_gui.ui.thumbnails import ThumbnailCache

        self.theme = ThemeManager(self.root)
        self.theme.apply(self.settings.theme)
        self.thumbnails = ThumbnailCache(self.paths.thumbnails_dir, self.tools, self.call_soon)
        self.window = MainWindow(self.root, self)
        self.root.geometry(self.settings.window_geometry or self._default_geometry())

        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        if sys.platform == "darwin":
            self.root.createcommand("::tk::mac::Quit", self.quit)
            self.root.createcommand("::tk::mac::ShowPreferences", self.open_settings)
        self.root.after(50, self._process_ui_calls)
        self.root.after(400, self._after_start)

    def run(self) -> None:
        self.root.mainloop()

    # ----------------------------------------------------------------------------------
    # Thread -> UI bridge
    # ----------------------------------------------------------------------------------

    def call_soon(self, fn: Callable[[], None]) -> None:
        """Run `fn` on the UI thread. Safe to call from any thread."""
        self._ui_calls.put(fn)

    def run_in_background(self, work: Callable[[], object], done: Callable[[object], None] | None = None,
                          failed: Callable[[Exception], None] | None = None) -> None:
        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                log.exception("Background task failed")
                if failed:
                    self.call_soon(lambda: failed(exc))
                return
            if done:
                self.call_soon(lambda: done(result))

        threading.Thread(target=runner, daemon=True).start()

    def _process_ui_calls(self) -> None:
        for _ in range(500):  # bounded, so the UI stays responsive under heavy traffic
            try:
                fn = self._ui_calls.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                log.exception("UI callback failed")
        self.root.after(60, self._process_ui_calls)

    # ----------------------------------------------------------------------------------
    # Downloads
    # ----------------------------------------------------------------------------------

    def start_downloads(self, requests: list) -> bool:
        """Queue download requests. Returns False if required tools are missing."""
        missing = [k for k in self.tools.missing_required() if k != DENO]  # Deno only warns
        if missing:
            names = ", ".join(TOOL_NAMES[k] for k in missing)
            if messagebox.askyesno(APP_NAME, f"{names} must be installed before downloading.\n\nInstall now?",
                                   parent=self.root):
                self.open_tools(install_missing=True)
            return False
        for request in requests:
            self.queue.add(request)
        self.window.show_downloads()
        return True

    def _on_download_notification(self, note: object) -> None:
        if isinstance(note, JobChanged):
            self.window.jobs.show(note.snapshot)
        elif isinstance(note, FileDownloaded):
            if self.settings.history_enabled:
                self._record_history(note.request, note.item.title, note.url, note.item.file_path,
                                     note.item.video_id, note.thumbnail_url)
        elif isinstance(note, JobFinished):
            snapshot = note.snapshot
            self.window.jobs.show(snapshot)
            if snapshot.state is JobState.FAILED and self.settings.history_enabled:
                self._record_history(note.request, snapshot.title, note.request.urls[0], "", snapshot.video_id,
                                     snapshot.thumbnail_url, error=snapshot.last_error)

    def _record_history(self, request: DownloadRequest, title: str, url: str, file_path: str, video_id: str,
                        thumbnail_url: str, error: str = "") -> None:
        entry = HistoryEntry(
            title=title or url, url=url, file_path=file_path, video_id=video_id, thumbnail_url=thumbnail_url,
            file_format=request.file_format, resolution=request.resolution,
            status="failed" if error else "completed", error=error, finished_at=time.time())
        self.history.add(entry)
        self.window.history.add_entry(entry)

    # ----------------------------------------------------------------------------------
    # Settings, tools, updates
    # ----------------------------------------------------------------------------------

    def save_settings(self) -> None:
        save_settings(self.settings, self.paths.settings_file)

    def apply_settings(self) -> None:
        """Called after the Settings window saved changes."""
        self.save_settings()
        self.theme.apply(self.settings.theme)
        self.window.form.load_defaults()
        self.window.history.reload()
        self.update_status_bar()

    def open_settings(self) -> None:
        from ytdlp_gui.ui.settings_dialog import SettingsDialog

        SettingsDialog(self)

    def open_tools(self, install_missing: bool = False) -> None:
        from ytdlp_gui.ui.tools_dialog import ToolsDialog

        if self._tools_dialog is None or not self._tools_dialog.winfo_exists():
            self._tools_dialog = ToolsDialog(self)
        self._tools_dialog.lift()
        self._tools_dialog.focus_set()
        if install_missing:
            self._tools_dialog.install_missing()

    def on_tools_changed(self) -> None:
        self.update_status_bar()

    def note_update_check(self, updates: list) -> None:
        """Remember the result of an update check and show it in the status bar."""
        self._updates = updates
        self.settings.last_update_check = time.time()
        self.save_settings()
        self.update_status_bar()

    def update_status_bar(self) -> None:
        missing = self.tools.missing_required()
        if self.settings.engine == "library":
            version = ytdlp_library_loader.loaded_version()
            engine = "yt-dlp library" + (f" {version}" if version else "")
        else:
            engine = "yt-dlp program"
        parts = [f"Engine: {engine}"]
        for key, label in ((FFMPEG, "FFmpeg"), (DENO, "Deno")):
            parts.append(f"{label} {'missing' if key in missing else '✓'}")
        text = "   ·   ".join(parts)
        if missing:
            self.window.set_status(text, "Install missing tools", lambda: self.open_tools(install_missing=True))
        elif self._updates:
            names = ", ".join(TOOL_NAMES[k] for k in self._updates)
            self.window.set_status(text, f"Updates available: {names}", self.open_tools)
        else:
            self.window.set_status(text)

    def _after_start(self) -> None:
        self.update_status_bar()
        if self.settings.engine == "library":  # import yt-dlp early so the first download starts fast
            self.run_in_background(ytdlp_library_loader.current_version, lambda _v: self.update_status_bar())

        installable = [k for k in self.tools.missing_required()
                       if k == YTDLP_LIBRARY or self.tools.source_of(k) == "managed"]
        if installable:
            names = " and ".join(TOOL_NAMES[k] for k in installable)
            if messagebox.askyesno(
                    "Finish setting up",
                    f"{APP_NAME} needs {names} to download and merge videos.\n\n"
                    "Download them now? This happens once; you can update them later from Tools & updates.",
                    parent=self.root):
                self.open_tools(install_missing=True)
        elif (self.settings.check_updates_on_startup
              and time.time() - self.settings.last_update_check > UPDATE_CHECK_INTERVAL):
            self.run_in_background(self._find_updates, self.note_update_check)

    def _find_updates(self) -> list:
        """Background update check: keys of app-managed tools with a newer version."""
        updates = []
        for tool in TOOLS:
            if tool.key != YTDLP_LIBRARY and self.tools.source_of(tool.key) != "managed":
                continue
            if tool.key == "ytdlp_program" and self.settings.engine != "cli":
                continue
            try:
                status = self.tools.status(tool.key)
                if status.installed_version and self.tools.is_newer(
                        tool.key, self.tools.latest_version(tool.key), status.installed_version):
                    updates.append(tool.key)
            except Exception as exc:
                log.info("Update check for %s failed: %s", tool.key, exc)
        return updates

    # ----------------------------------------------------------------------------------
    # Quitting / restarting
    # ----------------------------------------------------------------------------------

    def quit(self) -> None:
        if self.queue.active_count():
            if not messagebox.askyesno(APP_NAME, "Downloads are still running. Cancel them and quit?",
                                       parent=self.root):
                return
            self.queue.cancel_all()
        self.settings.window_geometry = self.root.geometry()
        self.save_settings()
        self._close_when_idle(time.monotonic() + 4)

    def _close_when_idle(self, deadline: float) -> None:
        """Give cancelled downloads a moment to stop their processes, then close."""
        if self.queue.active_count() and time.monotonic() < deadline:
            self.root.after(100, lambda: self._close_when_idle(deadline))
            return
        log.info("Exiting")
        self.root.destroy()

    def restart(self) -> None:
        if self.queue.active_count():
            messagebox.showinfo(APP_NAME, "Please wait until the downloads have finished.", parent=self.root)
            return
        self.settings.window_geometry = self.root.geometry()
        self.save_settings()
        if getattr(sys, "frozen", False):
            args = [sys.executable, *sys.argv[1:]]
        elif sys.argv and sys.argv[0].endswith("__main__.py"):  # started with "python -m ytdlp_gui"
            args = [sys.executable, "-m", "ytdlp_gui", *sys.argv[1:]]
        else:
            args = [sys.executable, *sys.argv]
        subprocess.Popen(args, close_fds=True)
        self.root.destroy()

    # ----------------------------------------------------------------------------------

    def _on_ui_exception(self, exc_type, exc_value, exc_tb) -> None:
        log.error("Unhandled UI error", exc_info=(exc_type, exc_value, exc_tb))
        messagebox.showerror(APP_NAME, f"Something went wrong:\n{exc_value}\n\nDetails are in {self.paths.log_file}",
                             parent=self.root)

    def _default_geometry(self) -> str:
        """980x780, shrunk to fit small screens (leaving room for task bars / the Dock)."""
        width = min(980, self.root.winfo_screenwidth() - 40)
        height = min(780, self.root.winfo_screenheight() - 100)
        return f"{width}x{height}"

    def _set_icon(self) -> None:
        from ytdlp_gui.ui.app_icon import png_bytes

        try:
            self._icon = tk.PhotoImage(data=base64.b64encode(png_bytes(64)))
            self.root.iconphoto(True, self._icon)
        except tk.TclError:
            pass


def _setup_logging(log_file) -> None:
    # Windowed builds have no console: give Python somewhere harmless to write.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not getattr(sys, "frozen", False):
        root.addHandler(logging.StreamHandler())
    threading.excepthook = lambda args: log.error(
        "Unhandled error in thread %s", args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _enable_windows_dpi_awareness() -> None:
    """Sharp (not blurry) text on high-DPI Windows screens."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main() -> None:
    App().run()
