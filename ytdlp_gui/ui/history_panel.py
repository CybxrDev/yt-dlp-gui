"""
The "History" tab: past downloads with their thumbnails.

Double-click opens a file. Select one or more rows to open, show in folder, copy links,
download again, or remove them (Delete key works too). "Clear all" empties the history.
When history is turned off in Settings, new downloads aren't recorded and a notice says so.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ytdlp_gui import APP_NAME
from ytdlp_gui.config.history import HistoryEntry
from ytdlp_gui.downloads.format_selection import describe
from ytdlp_gui.ui.formatting import format_timestamp
from ytdlp_gui.ui.thumbnails import HEIGHT
from ytdlp_gui.ui.widgets import open_path, reveal_in_folder

if TYPE_CHECKING:
    from ytdlp_gui.app import App


class HistoryPanel(ttk.Frame):
    COLUMNS = ("format", "date", "status", "folder")

    def __init__(self, master: tk.Misc, app: "App"):
        super().__init__(master)
        self.app = app

        toolbar = ttk.Frame(self, padding=(12, 8, 12, 4))
        toolbar.pack(fill="x")
        self.notice = ttk.Label(toolbar, style="Warning.TLabel",
                                text="History is off – new downloads aren't recorded (Settings → General).")
        ttk.Button(toolbar, text="Clear all", command=self._clear_all).pack(side="right")
        ttk.Button(toolbar, text="Remove", command=self._remove_selected).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="Download again", command=self._download_again).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="Copy link", command=self._copy_links).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="Show in folder", command=self._show_in_folder).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="Open", command=self._open_selected).pack(side="right")

        body = ttk.Frame(self, padding=(12, 0, 12, 8))
        body.pack(fill="both", expand=True)
        ttk.Style(self).configure("History.Treeview", rowheight=HEIGHT + 8)
        self.tree = ttk.Treeview(body, columns=self.COLUMNS, show="tree headings", selectmode="extended",
                                 style="History.Treeview", height=6)
        self.tree.heading("#0", text="Title", anchor="w")
        self.tree.heading("format", text="Format", anchor="w")
        self.tree.heading("date", text="Date", anchor="w")
        self.tree.heading("status", text="Status", anchor="w")
        self.tree.heading("folder", text="Folder", anchor="w")
        self.tree.column("#0", width=420, minwidth=200, stretch=True)
        self.tree.column("format", width=100, stretch=False)
        self.tree.column("date", width=130, stretch=False)
        self.tree.column("status", width=90, stretch=False)
        self.tree.column("folder", width=200, stretch=True)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda _e: self._open_selected())
        self.tree.bind("<Delete>", lambda _e: self._remove_selected())
        self.tree.bind("<BackSpace>", lambda _e: self._remove_selected())
        self.tree.bind("<Button-2>" if sys.platform == "darwin" else "<Button-3>", self._context_menu)
        if sys.platform == "darwin":
            self.tree.bind("<Control-Button-1>", self._context_menu)
        app.theme.on_change(lambda p: self.tree.tag_configure("failed", foreground=p.danger))

        self.reload()

    # ----------------------------------------------------------------------------------

    def reload(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for entry in self.app.history.entries:
            self._insert(entry, "end")
        self.refresh_notice()

    def add_entry(self, entry: HistoryEntry) -> None:
        self._insert(entry, 0)

    def refresh_notice(self) -> None:
        if self.app.settings.history_enabled:
            self.notice.pack_forget()
        else:
            self.notice.pack(side="left")

    def _insert(self, entry: HistoryEntry, index) -> None:
        failed = entry.status != "completed"
        folder = os.path.dirname(entry.file_path) if entry.file_path else ""
        self.tree.insert(
            "", index, iid=entry.entry_id, text="  " + (entry.title or entry.url),
            image=self.app.thumbnails.placeholder(),
            values=(describe(entry.file_format, entry.resolution) if entry.file_format else "",
                    format_timestamp(entry.finished_at), "Failed" if failed else "Done", folder),
            tags=("failed",) if failed else ())
        if entry.video_id:
            iid = entry.entry_id
            self.app.thumbnails.request(entry.video_id, entry.thumbnail_url,
                                        lambda image: self.tree.exists(iid) and self.tree.item(iid, image=image))

    def _selected(self) -> list:
        ids = set(self.tree.selection())
        return [e for e in self.app.history.entries if e.entry_id in ids]

    # --- actions -------------------------------------------------------------------------

    def _open_selected(self) -> None:
        for entry in self._selected()[:5]:
            if entry.file_path and os.path.exists(entry.file_path):
                open_path(entry.file_path)
            else:
                messagebox.showinfo(APP_NAME, f"The file for “{entry.title}” isn't there any more "
                                              "(it was moved or deleted).", parent=self)

    def _show_in_folder(self) -> None:
        selected = self._selected()
        if selected:
            reveal_in_folder(selected[0].file_path or self.app.settings.download_dir)

    def _copy_links(self) -> None:
        links = [e.url for e in self._selected() if e.url]
        if links:
            self.clipboard_clear()
            self.clipboard_append("\n".join(links))

    def _download_again(self) -> None:
        links = [e.url for e in self._selected() if e.url]
        if links:
            self.app.window.form.links.set_text("\n".join(links))
            self.app.window.form.links.focus_set()

    def _remove_selected(self) -> None:
        selected = self._selected()
        if not selected:
            return
        removed = self.app.history.remove({e.entry_id for e in selected})
        self.tree.delete(*[e.entry_id for e in removed])
        still_used = {e.video_id for e in self.app.history.entries}
        for entry in removed:
            if entry.video_id and entry.video_id not in still_used:
                self.app.thumbnails.forget(entry.video_id)

    def _clear_all(self) -> None:
        if not self.app.history.entries:
            return
        if messagebox.askyesno(APP_NAME, "Remove every entry from the history?\n(Downloaded files are not deleted.)",
                               parent=self):
            for entry in self.app.history.entries:
                if entry.video_id:
                    self.app.thumbnails.forget(entry.video_id)
            self.app.history.clear()
            self.reload()

    def _context_menu(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Open", command=self._open_selected)
        menu.add_command(label="Show in folder", command=self._show_in_folder)
        menu.add_command(label="Copy link", command=self._copy_links)
        menu.add_command(label="Download again", command=self._download_again)
        menu.add_separator()
        menu.add_command(label="Remove from history", command=self._remove_selected)
        menu.tk_popup(event.x_root, event.y_root)
