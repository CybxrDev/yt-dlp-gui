"""
The "Tools & updates" window: versions of yt-dlp, FFmpeg and Deno, update checks and
one-click install/update for the copies this app manages.

All slow work (running programs for their version, network requests, downloads) happens
in the background via App.run_in_background; this window only updates labels.
"""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ytdlp_gui import APP_NAME, APP_UPDATE_REPO, APP_VERSION
from ytdlp_gui.tools import tool_sources
from ytdlp_gui.tools.tool_manager import DENO, FFMPEG, TOOLS, YTDLP_LIBRARY, YTDLP_PROGRAM, ToolStatus

if TYPE_CHECKING:
    from ytdlp_gui.app import App

_APP_KEY = "app"


class ToolsDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app.root)
        self.app = app
        self.title(f"{APP_NAME} – Tools & updates")
        self.configure(background=app.theme.palette.bg)
        self.transient(app.root)
        self.minsize(780, 0)
        self.status: dict = {}
        self.latest: dict = {}
        self.busy = False
        self._cancel = threading.Event()
        self._restart_needed = False

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Tools & updates", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(body, style="Muted.TLabel", wraplength=740, justify="left",
                  text="YouTube changes often, so keep yt-dlp up to date. Tools marked “Downloaded by app” "
                       "can be installed and updated here; others are managed by you (see Settings → "
                       "Engine & tools).").pack(anchor="w", pady=(2, 12))

        self.table = ttk.Frame(body)
        self.table.pack(fill="x")
        self.rows: dict = {}
        headers = ("Component", "Source", "Installed", "Latest", "")
        for col, text in enumerate(headers):
            ttk.Label(self.table, text=text, style="Small.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 14))
        self.table.columnconfigure(0, weight=1)
        keys = [t.key for t in TOOLS] + ([_APP_KEY] if APP_UPDATE_REPO else [])
        for index, key in enumerate(keys, start=1):
            self._make_row(index, key)

        self.note = ttk.Label(body, style="Warning.TLabel", wraplength=740, justify="left")
        self.note.pack(anchor="w", pady=(10, 0))

        progress = ttk.Frame(body)
        progress.pack(fill="x", pady=(12, 0))
        self.progress_bar = ttk.Progressbar(progress, maximum=1000)
        self.progress_bar.pack(fill="x")
        self.progress_text = ttk.Label(progress, style="Small.TLabel")
        self.progress_text.pack(anchor="w", pady=(4, 0))

        buttons = ttk.Frame(self, padding=(16, 0, 16, 16))
        buttons.pack(fill="x")
        self.check_button = ttk.Button(buttons, text="Check for updates", command=self.check_for_updates)
        self.check_button.pack(side="left")
        self.update_all_button = ttk.Button(buttons, text="Update all", style="Accent.TButton",
                                            command=self._update_all, state="disabled")
        self.update_all_button.pack(side="left", padx=8)
        self.revert_button = ttk.Button(buttons, text="Use built-in yt-dlp", command=self._revert_library)
        self.restart_button = ttk.Button(buttons, text="Restart app now", command=self.app.restart)
        ttk.Button(buttons, text="Close", command=self._close).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.refresh_installed()
        self.check_for_updates()

    # ----------------------------------------------------------------------------------
    # Table
    # ----------------------------------------------------------------------------------

    def _make_row(self, row: int, key: str) -> None:
        if key == _APP_KEY:
            name, purpose = APP_NAME, "This app"
        else:
            info = next(t for t in TOOLS if t.key == key)
            name, purpose = info.name, info.purpose
        cell = ttk.Frame(self.table)
        cell.grid(row=row, column=0, sticky="w", pady=5, padx=(0, 14))
        ttk.Label(cell, text=name, style="Bold.TLabel").pack(anchor="w")
        ttk.Label(cell, text=purpose, style="Small.TLabel").pack(anchor="w")
        widgets = {
            "source": ttk.Label(self.table, text="…"),
            "installed": ttk.Label(self.table, text="…"),
            "latest": ttk.Label(self.table, text="–", style="Muted.TLabel"),
            "button": ttk.Button(self.table, text="…", width=12, state="disabled",
                                 command=lambda k=key: self._row_action(k)),
        }
        for col, name_ in enumerate(("source", "installed", "latest", "button"), start=1):
            widgets[name_].grid(row=row, column=col, sticky="w", padx=(0, 14))
        self.rows[key] = widgets

    def _render(self) -> None:
        notes = []
        updates = 0
        for key, w in self.rows.items():
            status: ToolStatus | None = self.status.get(key)
            latest = self.latest.get(key)
            if key == _APP_KEY:
                w["source"].configure(text="–")
                w["installed"].configure(text=APP_VERSION)
                w["latest"].configure(text=latest or "–")
                newer = bool(latest) and _newer(latest, APP_VERSION)
                w["button"].configure(text="Get update" if newer else "Up to date",
                                      state="normal" if newer else "disabled")
                continue
            if status is None:
                continue
            installed = status.installed_version
            w["source"].configure(text=status.source_label)
            w["installed"].configure(text=installed or "not found",
                                     style="TLabel" if installed else "Error.TLabel")
            w["latest"].configure(text=latest or "–")
            newer = self.app.tools.is_newer(key, latest, installed)
            if not status.can_update:
                text, state = "Managed by you", "disabled"
            elif not installed:
                text, state = "Install", "normal"
            elif newer:
                text, state = "Update", "normal"
                updates += 1
            else:
                text, state = ("Up to date" if latest else "Reinstall"), ("disabled" if latest else "normal")
            w["button"].configure(text=text, state="disabled" if self.busy else state)
            if status.note:
                notes.append(status.note)
                if "restart" in status.note.lower():
                    self._restart_needed = True
        self.note.configure(text="\n".join(notes))
        self.update_all_button.configure(state="normal" if updates and not self.busy else "disabled")
        self.check_button.configure(state="disabled" if self.busy else "normal")
        if self._restart_needed:
            self.restart_button.pack(side="left", padx=8)
        if (self.app.paths.ytdlp_library_dir / "yt_dlp").exists() and not self.busy:
            self.revert_button.pack(side="left", padx=8)
        else:
            self.revert_button.pack_forget()

    # ----------------------------------------------------------------------------------
    # Background work
    # ----------------------------------------------------------------------------------

    def refresh_installed(self) -> None:
        """Read installed versions (runs the programs, so it happens in the background)."""
        def work() -> dict:
            return {t.key: self.app.tools.status(t.key) for t in TOOLS}

        def done(result: dict) -> None:
            if self.winfo_exists():
                self.status = result
                self._render()
                self._report_to_app()

        self.app.run_in_background(work, done)

    def _report_to_app(self) -> None:
        """Tell the main window whether updates are available (once versions are known)."""
        if self.status and self.latest:
            self.app.note_update_check(self.updates_available())

    def check_for_updates(self) -> None:
        self._set_progress("Checking for updates…", None)
        self.check_button.configure(state="disabled")

        def work() -> tuple:
            latest, errors = {}, []
            for key in [t.key for t in TOOLS] + ([_APP_KEY] if APP_UPDATE_REPO else []):
                try:
                    if key == _APP_KEY:
                        latest[key] = tool_sources.app_release(APP_UPDATE_REPO).version
                    else:
                        latest[key] = self.app.tools.latest_version(key)
                except tool_sources.SourceUnavailable:
                    continue
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
            return latest, errors

        def done(result: tuple) -> None:
            if not self.winfo_exists():
                return
            self.latest, errors = result
            self._render()
            self._set_progress("Could not check: " + "; ".join(errors) if errors else "Check complete.", 0)
            self._report_to_app()

        self.app.run_in_background(work, done)

    def updates_available(self) -> list:
        return [k for k, s in self.status.items()
                if s.can_update and self.app.tools.is_newer(k, self.latest.get(k), s.installed_version)]

    def install(self, keys: list) -> None:
        """Install/update the given tools one after another."""
        if self.busy or not keys:
            return
        if self.app.queue.active_count():
            messagebox.showinfo(APP_NAME, "Please wait until the current downloads have finished.", parent=self)
            return
        self.busy = True
        self._cancel.clear()
        self._render()

        def progress(message: str, fraction) -> None:
            self.app.call_soon(lambda: self._set_progress(message, fraction))

        def work() -> list:
            results = []
            for key in keys:
                try:
                    version = self.app.tools.install(key, progress, self._cancel)
                    results.append((key, version, None))
                except Exception as exc:
                    results.append((key, None, str(exc)))
            return results

        def done(results: list) -> None:
            self.busy = False
            failed = [f"{_name(k)}: {err}" for k, _v, err in results if err]
            installed = [f"{_name(k)} {v}" for k, v, err in results if not err]
            if any(k == YTDLP_LIBRARY and not err for k, _v, err in results):
                self._restart_needed = True
            message = ("Installed " + ", ".join(installed) + ". ") if installed else ""
            message += ("Problems: " + "; ".join(failed)) if failed else ""
            if self.winfo_exists():
                self._set_progress(message.strip() or "Done.", 0)
                self.refresh_installed()
            if failed:
                messagebox.showerror(APP_NAME, "\n".join(failed), parent=self if self.winfo_exists() else None)
            self.app.on_tools_changed()

        self.app.run_in_background(work, done)

    def install_missing(self) -> None:
        missing = [k for k in self.app.tools.missing_required()
                   if k == YTDLP_LIBRARY or self.app.tools.source_of(k) == "managed"]
        self.install(missing)

    # ----------------------------------------------------------------------------------
    # Buttons
    # ----------------------------------------------------------------------------------

    def _row_action(self, key: str) -> None:
        if key == _APP_KEY:
            webbrowser.open(f"https://github.com/{APP_UPDATE_REPO}/releases/latest")
        else:
            self.install([key])

    def _update_all(self) -> None:
        self.install(self.updates_available())

    def _revert_library(self) -> None:
        if messagebox.askyesno(APP_NAME, "Remove the downloaded yt-dlp update and go back to the version built into "
                                         "the app? This takes effect after a restart.", parent=self):
            self.app.tools.remove_library_update()
            self._restart_needed = True
            self.refresh_installed()

    def _set_progress(self, message: str, fraction) -> None:
        if not self.winfo_exists():
            return
        self.progress_text.configure(text=message)
        if fraction is None:
            if str(self.progress_bar.cget("mode")) != "indeterminate":
                self.progress_bar.configure(mode="indeterminate")
                self.progress_bar.start(12)
        else:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate", value=fraction * 1000)

    def _close(self) -> None:
        if self.busy and not messagebox.askyesno(APP_NAME, "An installation is running. Stop it and close?",
                                                 parent=self):
            return
        self._cancel.set()
        self.destroy()


def _name(key: str) -> str:
    return {YTDLP_LIBRARY: "yt-dlp library", YTDLP_PROGRAM: "yt-dlp program", FFMPEG: "FFmpeg",
            DENO: "Deno"}.get(key, key)


def _newer(latest: str, current: str) -> bool:
    def parts(v: str) -> tuple:
        return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))
    return parts(latest) > parts(current)
