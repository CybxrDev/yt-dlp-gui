"""
The top of the window: the links box and the options for the next download.

The options start from the defaults in Settings. Changing them here affects only the
downloads started from this form ("per download"); "Save as defaults" makes them the
new defaults, "Reset to defaults" brings the defaults back.

Pasting several links creates one job per link. Importing a .txt file creates a single
job containing every link in the file.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from ytdlp_gui import APP_NAME
from ytdlp_gui.downloads.filename_pattern import DEFAULT_PATTERN, TOKENS, preview
from ytdlp_gui.downloads.format_selection import FORMAT_CHOICES, RESOLUTION_CHOICES, is_audio_format
from ytdlp_gui.downloads.models import DownloadRequest
from ytdlp_gui.downloads.url_parsing import extract_urls, read_url_file
from ytdlp_gui.ui.widgets import PlaceholderText, Tooltip

if TYPE_CHECKING:
    from ytdlp_gui.app import App

_FORMAT_BY_LABEL = {label: key for key, label in FORMAT_CHOICES.items()}
_RESOLUTION_BY_LABEL = {label: key for key, label in RESOLUTION_CHOICES.items()}

_PATTERN_HELP = (
    "How downloaded files are named. Words in [brackets] are replaced with details of "
    "each video, e.g. \"[title] - [id]\". The extension is added automatically. Use "
    "\"/\" to create sub-folders, e.g. \"[playlist]/[index] - [title]\". Use Insert ▾ to "
    "add a token."
)


class DownloadForm(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "App"):
        super().__init__(master, padding=(16, 10, 16, 6))
        self.app = app
        self.format_var = tk.StringVar()
        self.resolution_var = tk.StringVar()
        self.folder_var = tk.StringVar()
        self.pattern_var = tk.StringVar()
        self.playlist_var = tk.BooleanVar()
        self.preview_var = tk.StringVar()
        self.notice_var = tk.StringVar()
        self._build()
        self.load_defaults()
        self.pattern_var.trace_add("write", lambda *_: self._update_preview())
        self.format_var.trace_add("write", lambda *_: self._on_format_changed())

    # ----------------------------------------------------------------------------------
    # Layout
    # ----------------------------------------------------------------------------------

    def _build(self) -> None:
        theme = self.app.theme
        self.columnconfigure(1, weight=1)

        # Links
        header = ttk.Frame(self)
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(header, text="Links", style="Bold.TLabel").pack(side="left")
        ttk.Label(header, text="videos, Shorts, playlists or channels – one per line",
                  style="Small.TLabel").pack(side="left", padx=8)
        ttk.Button(header, text="Import .txt…", command=self._import_txt).pack(side="right")
        ttk.Button(header, text="Paste", command=self._paste).pack(side="right", padx=6)
        ttk.Button(header, text="Clear", command=lambda: self.links.set_text("")).pack(side="right")

        self.links = PlaceholderText(self, theme, "Paste a link here, e.g. https://www.youtube.com/watch?v=…", height=3)
        self.links.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 10))
        start_key = "<Command-Return>" if sys.platform == "darwin" else "<Control-Return>"
        self.links.bind(start_key, lambda _e: (self.start_download(), "break")[1])

        # Format, quality, playlist
        options = ttk.Frame(self)
        options.grid(row=2, column=0, columnspan=3, sticky="ew")
        ttk.Label(options, text="Format").pack(side="left")
        self.format_box = ttk.Combobox(options, textvariable=self.format_var, state="readonly", width=18,
                                       values=list(FORMAT_CHOICES.values()))
        self.format_box.pack(side="left", padx=(8, 18))
        ttk.Label(options, text="Quality").pack(side="left")
        self.resolution_box = ttk.Combobox(options, textvariable=self.resolution_var, state="readonly", width=16,
                                           values=list(RESOLUTION_CHOICES.values()))
        self.resolution_box.pack(side="left", padx=(8, 18))
        Tooltip(self.resolution_box, "The best quality up to this resolution. If a video isn't available "
                                     "that high, the best lower one is used.", theme)
        playlist = ttk.Checkbutton(options, text="Whole playlist", variable=self.playlist_var)
        playlist.pack(side="left")
        Tooltip(playlist, "For a link to a video inside a playlist (…watch?v=…&list=…): download the whole "
                          "playlist instead of only that video. Playlist and channel links always download "
                          "everything.", theme)

        # Folder
        ttk.Label(self, text="Save to").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(self, textvariable=self.folder_var).grid(row=3, column=1, sticky="ew", padx=8, pady=(10, 0))
        ttk.Button(self, text="Browse…", command=self._browse).grid(row=3, column=2, sticky="ew", pady=(10, 0))

        # File name pattern
        ttk.Label(self, text="File name").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.pattern_entry = ttk.Entry(self, textvariable=self.pattern_var)
        self.pattern_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=(8, 0))
        Tooltip(self.pattern_entry, _PATTERN_HELP, theme)
        insert = ttk.Menubutton(self, text="Insert ▾")
        menu = tk.Menu(insert, tearoff=False)
        for name, token in TOKENS.items():
            if name not in ("url_id", "ext"):
                menu.add_command(label=f"[{name}]  –  {token.description}",
                                 command=lambda n=name: self._insert_token(n))
        insert["menu"] = menu
        insert.grid(row=4, column=2, sticky="ew", pady=(8, 0))
        ttk.Label(self, textvariable=self.preview_var, style="Small.TLabel").grid(
            row=5, column=1, columnspan=2, sticky="w", padx=8, pady=(2, 0))

        # Actions
        actions = ttk.Frame(self)
        actions.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Reset to defaults", style="Link.TButton",
                   command=self.load_defaults).pack(side="left")
        ttk.Button(actions, text="Save as defaults", style="Link.TButton",
                   command=self.save_as_defaults).pack(side="left", padx=14)
        ttk.Label(actions, textvariable=self.notice_var, style="Success.TLabel").pack(side="left")
        self.download_button = ttk.Button(actions, text="Download", style="Accent.TButton",
                                          command=self.start_download)
        self.download_button.pack(side="right")

    # ----------------------------------------------------------------------------------
    # Defaults
    # ----------------------------------------------------------------------------------

    def load_defaults(self) -> None:
        s = self.app.settings
        self.format_var.set(FORMAT_CHOICES[s.file_format])
        self.resolution_var.set(RESOLUTION_CHOICES[s.resolution])
        self.folder_var.set(s.download_dir)
        self.pattern_var.set(s.filename_pattern)
        self.playlist_var.set(s.whole_playlist)
        self._on_format_changed()

    def save_as_defaults(self) -> None:
        s = self.app.settings
        s.file_format = self._file_format()
        s.resolution = self._resolution()
        s.download_dir = self.folder_var.get().strip() or s.download_dir
        s.filename_pattern = self.pattern_var.get().strip() or DEFAULT_PATTERN
        s.whole_playlist = self.playlist_var.get()
        self.app.save_settings()
        self._flash("Saved as defaults")

    # ----------------------------------------------------------------------------------
    # Starting downloads
    # ----------------------------------------------------------------------------------

    def start_download(self) -> None:
        urls = extract_urls(self.links.get_text())
        if not urls:
            messagebox.showinfo(APP_NAME, "Paste at least one link first.", parent=self)
            return
        requests = []
        for url in urls:
            request = self._make_request([url], url)
            if request is None:
                return
            requests.append(request)
        if self.app.start_downloads(requests):
            self.links.set_text("")

    def _import_txt(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Choose a text file with links",
                                          filetypes=[("Text files", "*.txt"), ("All files", "*")])
        if not path:
            return
        try:
            urls = read_url_file(Path(path))
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not read the file:\n{exc}", parent=self)
            return
        if not urls:
            messagebox.showinfo(APP_NAME, "No links were found in that file.", parent=self)
            return
        label = f"{Path(path).name} – {len(urls)} link{'s' if len(urls) != 1 else ''}"
        request = self._make_request(urls, label)
        if request is not None:
            self.app.start_downloads([request])

    def _make_request(self, urls: list, label: str) -> DownloadRequest | None:
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showinfo(APP_NAME, "Choose a folder to save to.", parent=self)
            return None
        folder_path = Path(folder).expanduser()
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Can't use that folder:\n{exc}", parent=self)
            return None
        return DownloadRequest(
            urls=urls,
            output_dir=str(folder_path),
            file_format=self._file_format(),
            resolution=self._resolution(),
            filename_pattern=self.pattern_var.get().strip() or DEFAULT_PATTERN,
            whole_playlist=self.playlist_var.get(),
            label=label,
        )

    # ----------------------------------------------------------------------------------
    # Small helpers
    # ----------------------------------------------------------------------------------

    def _file_format(self) -> str:
        return _FORMAT_BY_LABEL.get(self.format_var.get(), "mp4")

    def _resolution(self) -> str:
        return _RESOLUTION_BY_LABEL.get(self.resolution_var.get(), "best")

    def _on_format_changed(self) -> None:
        audio = is_audio_format(self._file_format())
        self.resolution_box.configure(state="disabled" if audio else "readonly")
        self._update_preview()

    def _update_preview(self) -> None:
        self.preview_var.set("Example: " + preview(self.pattern_var.get(), self._file_format()))

    def _insert_token(self, name: str) -> None:
        self.pattern_entry.insert("insert", f"[{name}]")
        self.pattern_entry.focus_set()

    def _paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            return
        existing = self.links.get_text().strip()
        self.links.set_text(f"{existing}\n{text}" if existing else text)

    def _browse(self) -> None:
        start = self.folder_var.get().strip() or str(Path.home())
        folder = filedialog.askdirectory(parent=self, initialdir=start, title="Choose where to save downloads")
        if folder:
            self.folder_var.set(folder)

    def _flash(self, text: str) -> None:
        self.notice_var.set(text)
        self.after(2500, lambda: self.notice_var.set(""))
