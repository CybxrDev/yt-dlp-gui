"""
The Settings window.

Tabs:
    Downloads         defaults for new downloads and what gets embedded in files
    General           theme, history, update checks
    Engine & tools    how yt-dlp runs (library or program) and where FFmpeg/Deno/yt-dlp come from

Changes are applied when "Save" is clicked. Every field maps to one attribute of
config.settings.Settings.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from ytdlp_gui import APP_NAME
from ytdlp_gui.config.settings import COOKIE_BROWSERS, DEFAULT_FILENAME_PATTERN
from ytdlp_gui.downloads.engines import ENGINE_LABELS
from ytdlp_gui.downloads.filename_pattern import preview
from ytdlp_gui.downloads.format_selection import FORMAT_CHOICES, RESOLUTION_CHOICES
from ytdlp_gui.tools.platform_info import IS_WINDOWS
from ytdlp_gui.ui.widgets import Tooltip

if TYPE_CHECKING:
    from ytdlp_gui.app import App

_SOURCE_LABELS = {
    "managed": "Downloaded by this app",
    "system": "Installed on this computer (PATH)",
    "custom": "Custom location…",
}
_SOURCE_BY_LABEL = {v: k for k, v in _SOURCE_LABELS.items()}
_BROWSER_LABELS = {b: (b.capitalize() if b else "None (recommended)") for b in COOKIE_BROWSERS}
_BROWSER_BY_LABEL = {v: k for k, v in _BROWSER_LABELS.items()}


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app.root)
        self.app = app
        self.title(f"{APP_NAME} – Settings")
        self.configure(background=app.theme.palette.bg)
        self.transient(app.root)
        self.resizable(True, False)
        s = app.settings

        # Variables (one per setting)
        self.v = {
            "download_dir": tk.StringVar(value=s.download_dir),
            "file_format": tk.StringVar(value=FORMAT_CHOICES[s.file_format]),
            "resolution": tk.StringVar(value=RESOLUTION_CHOICES[s.resolution]),
            "filename_pattern": tk.StringVar(value=s.filename_pattern),
            "whole_playlist": tk.BooleanVar(value=s.whole_playlist),
            "embed_thumbnail": tk.BooleanVar(value=s.embed_thumbnail),
            "embed_metadata": tk.BooleanVar(value=s.embed_metadata),
            "embed_chapters": tk.BooleanVar(value=s.embed_chapters),
            "max_parallel_downloads": tk.IntVar(value=s.max_parallel_downloads),
            "theme": tk.StringVar(value=s.theme),
            "history_enabled": tk.BooleanVar(value=s.history_enabled),
            "check_updates_on_startup": tk.BooleanVar(value=s.check_updates_on_startup),
            "engine": tk.StringVar(value=s.engine),
            "ytdlp_cli_source": tk.StringVar(value=_SOURCE_LABELS[s.ytdlp_cli_source]),
            "ytdlp_cli_path": tk.StringVar(value=s.ytdlp_cli_path),
            "ffmpeg_source": tk.StringVar(value=_SOURCE_LABELS[s.ffmpeg_source]),
            "ffmpeg_path": tk.StringVar(value=s.ffmpeg_path),
            "js_runtime_source": tk.StringVar(value=_SOURCE_LABELS[s.js_runtime_source]),
            "js_runtime_path": tk.StringVar(value=s.js_runtime_path),
            "allow_remote_components": tk.BooleanVar(value=s.allow_remote_components),
            "cookies_from_browser": tk.StringVar(value=_BROWSER_LABELS.get(s.cookies_from_browser, "")),
        }
        self.preview_var = tk.StringVar()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        notebook.add(self._downloads_tab(notebook), text="Downloads")
        notebook.add(self._general_tab(notebook), text="General")
        notebook.add(self._engine_tab(notebook), text="Engine & tools")

        buttons = ttk.Frame(self, padding=12)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=8)

        self.v["filename_pattern"].trace_add("write", lambda *_: self._update_preview())
        self._update_preview()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    # ----------------------------------------------------------------------------------
    # Tabs
    # ----------------------------------------------------------------------------------

    def _downloads_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        tab.columnconfigure(1, weight=1)
        row = 0
        ttk.Label(tab, text="Default folder").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.v["download_dir"], width=48).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(tab, text="Browse…", command=self._browse_folder).grid(row=row, column=2)
        row += 1
        ttk.Label(tab, text="Default format").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(tab, textvariable=self.v["file_format"], values=list(FORMAT_CHOICES.values()),
                     state="readonly", width=22).grid(row=row, column=1, sticky="w", padx=8)
        row += 1
        ttk.Label(tab, text="Default quality").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(tab, textvariable=self.v["resolution"], values=list(RESOLUTION_CHOICES.values()),
                     state="readonly", width=22).grid(row=row, column=1, sticky="w", padx=8)
        row += 1
        ttk.Label(tab, text="Default file name").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(tab, textvariable=self.v["filename_pattern"]).grid(row=row, column=1, sticky="ew", padx=8)
        row += 1
        ttk.Label(tab, textvariable=self.preview_var, style="Small.TLabel").grid(row=row, column=1, sticky="w", padx=8)
        row += 1
        ttk.Checkbutton(tab, text="For a video inside a playlist, download the whole playlist",
                        variable=self.v["whole_playlist"]).grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 2))
        row += 1
        ttk.Separator(tab).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        ttk.Checkbutton(tab, text="Embed the thumbnail as cover art (MP4, MKV, MP3, M4A, Opus, FLAC)",
                        variable=self.v["embed_thumbnail"]).grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        row += 1
        ttk.Checkbutton(tab, text="Embed metadata (title, channel, date, description)",
                        variable=self.v["embed_metadata"]).grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        row += 1
        ttk.Checkbutton(tab, text="Embed chapters (video formats)",
                        variable=self.v["embed_chapters"]).grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
        row += 1
        ttk.Separator(tab).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        ttk.Label(tab, text="Downloads at the same time").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(tab, from_=1, to=5, width=5, state="readonly",
                    textvariable=self.v["max_parallel_downloads"]).grid(row=row, column=1, sticky="w", padx=8)
        return tab

    def _general_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        ttk.Label(tab, text="Appearance", style="Bold.TLabel").pack(anchor="w")
        themes = ttk.Frame(tab)
        themes.pack(anchor="w", pady=(4, 14))
        for value, label in (("system", "Follow the system"), ("light", "Light"), ("dark", "Dark")):
            ttk.Radiobutton(themes, text=label, value=value, variable=self.v["theme"]).pack(side="left", padx=(0, 16))

        ttk.Label(tab, text="History", style="Bold.TLabel").pack(anchor="w")
        history = ttk.Frame(tab)
        history.pack(anchor="w", fill="x", pady=(4, 14))
        ttk.Checkbutton(history, text="Keep a history of downloads",
                        variable=self.v["history_enabled"]).pack(side="left")
        ttk.Button(history, text="Clear history now", command=self._clear_history).pack(side="left", padx=16)

        ttk.Label(tab, text="Updates", style="Bold.TLabel").pack(anchor="w")
        ttk.Checkbutton(tab, text="Check for updates of yt-dlp, FFmpeg and Deno when the app starts (once a day)",
                        variable=self.v["check_updates_on_startup"]).pack(anchor="w", pady=4)
        return tab

    def _engine_tab(self, parent: tk.Misc) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=16)
        tab.columnconfigure(2, weight=1)
        ttk.Label(tab, text="Download engine", style="Bold.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Radiobutton(tab, text=ENGINE_LABELS["library"] + " – recommended", value="library",
                        variable=self.v["engine"]).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Radiobutton(tab, text=ENGINE_LABELS["cli"] + " – independent of this app's code", value="cli",
                        variable=self.v["engine"]).grid(row=2, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Label(tab, style="Small.TLabel", wraplength=560, justify="left",
                  text="The program engine starts the yt-dlp executable for every link, so downloads keep working "
                       "even if this app is no longer updated: update or replace that executable on its own.").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(2, 12))

        ttk.Label(tab, text="Where each tool comes from", style="Bold.TLabel").grid(row=4, column=0, columnspan=4, sticky="w")
        self._tool_row(tab, 5, "yt-dlp program", "ytdlp_cli_source", "ytdlp_cli_path")
        self._tool_row(tab, 6, "FFmpeg", "ffmpeg_source", "ffmpeg_path")
        self._tool_row(tab, 7, "JavaScript (Deno)", "js_runtime_source", "js_runtime_path")
        ttk.Label(tab, style="Small.TLabel", wraplength=560, justify="left",
                  text="FFmpeg merges video and audio and converts files. Deno (or Node.js / Bun) lets yt-dlp solve "
                       "YouTube's player challenges; without it some videos fail or only low qualities appear.").grid(
            row=8, column=0, columnspan=4, sticky="w", pady=(2, 12))

        ttk.Label(tab, text="Advanced", style="Bold.TLabel").grid(row=9, column=0, columnspan=4, sticky="w")
        remote = ttk.Checkbutton(tab, text="Let yt-dlp fetch its YouTube challenge scripts from GitHub when needed",
                                 variable=self.v["allow_remote_components"])
        remote.grid(row=10, column=0, columnspan=4, sticky="w", pady=4)
        Tooltip(remote, "Only used if the scripts bundled with yt-dlp don't match its version "
                        "(e.g. a system-wide yt-dlp installed without them).", self.app.theme)
        ttk.Label(tab, text="Browser cookies").grid(row=11, column=0, sticky="w", pady=4)
        cookies = ttk.Combobox(tab, textvariable=self.v["cookies_from_browser"], state="readonly", width=20,
                               values=list(_BROWSER_LABELS.values()))
        cookies.grid(row=11, column=1, sticky="w", padx=8)
        Tooltip(cookies, "Optional and off by default – no account or login is needed. Choosing a browser lets "
                         "yt-dlp use its cookies, which can help with age-restricted or members-only videos.",
                self.app.theme)
        return tab

    def _tool_row(self, tab: ttk.Frame, row: int, label: str, source_key: str, path_key: str) -> None:
        ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", pady=4)
        source = ttk.Combobox(tab, textvariable=self.v[source_key], state="readonly", width=30,
                              values=list(_SOURCE_LABELS.values()))
        source.grid(row=row, column=1, sticky="w", padx=8)
        path_entry = ttk.Entry(tab, textvariable=self.v[path_key], width=30)
        path_entry.grid(row=row, column=2, sticky="ew")
        browse = ttk.Button(tab, text="Browse…", command=lambda: self._browse_program(path_key))
        browse.grid(row=row, column=3, padx=(6, 0))

        def sync(*_):
            custom = _SOURCE_BY_LABEL.get(self.v[source_key].get()) == "custom"
            path_entry.configure(state="normal" if custom else "disabled")
            browse.configure(state="normal" if custom else "disabled")

        self.v[source_key].trace_add("write", sync)
        sync()

    # ----------------------------------------------------------------------------------
    # Actions
    # ----------------------------------------------------------------------------------

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, initialdir=self.v["download_dir"].get())
        if folder:
            self.v["download_dir"].set(folder)

    def _browse_program(self, key: str) -> None:
        types = [("Programs", "*.exe"), ("All files", "*")] if IS_WINDOWS else [("All files", "*")]
        path = filedialog.askopenfilename(parent=self, title="Choose the program file", filetypes=types)
        if path:
            self.v[key].set(path)

    def _update_preview(self) -> None:
        self.preview_var.set("Example: " + preview(self.v["filename_pattern"].get(), "mp4"))

    def _clear_history(self) -> None:
        if messagebox.askyesno(APP_NAME, "Remove every entry from the history?\n(Downloaded files are not deleted.)",
                               parent=self):
            self.app.history.clear()
            self.app.window.history.reload()

    def _save(self) -> None:
        s = self.app.settings
        old_history_enabled = s.history_enabled
        v = {k: var.get() for k, var in self.v.items()}
        s.download_dir = v["download_dir"].strip() or s.download_dir
        s.file_format = {lbl: k for k, lbl in FORMAT_CHOICES.items()}[v["file_format"]]
        s.resolution = {lbl: k for k, lbl in RESOLUTION_CHOICES.items()}[v["resolution"]]
        s.filename_pattern = v["filename_pattern"].strip() or DEFAULT_FILENAME_PATTERN
        for key in ("whole_playlist", "embed_thumbnail", "embed_metadata", "embed_chapters", "history_enabled",
                    "check_updates_on_startup", "allow_remote_components"):
            setattr(s, key, bool(v[key]))
        s.max_parallel_downloads = int(v["max_parallel_downloads"])
        s.theme = v["theme"]
        s.engine = v["engine"]
        for source_key, path_key in (("ytdlp_cli_source", "ytdlp_cli_path"), ("ffmpeg_source", "ffmpeg_path"),
                                     ("js_runtime_source", "js_runtime_path")):
            setattr(s, source_key, _SOURCE_BY_LABEL[v[source_key]])
            setattr(s, path_key, v[path_key].strip())
        s.cookies_from_browser = _BROWSER_BY_LABEL.get(v["cookies_from_browser"], "")
        s.validate()

        if old_history_enabled and not s.history_enabled and self.app.history.entries:
            if messagebox.askyesno(APP_NAME, "History is now off. Also delete the existing history?", parent=self):
                self.app.history.clear()
        self.destroy()
        self.app.apply_settings()
