"""
Main window layout, top to bottom:

    header       app name, "Tools & updates" and "Settings" buttons
    form         links box + per-download options (download_form.py)
    tabs         "Downloads" (jobs_panel.py) and "History" (history_panel.py)
    status bar   engine and tool status, plus a shortcut when something needs attention
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Callable, Optional

from ytdlp_gui import APP_NAME
from ytdlp_gui.ui.download_form import DownloadForm
from ytdlp_gui.ui.history_panel import HistoryPanel
from ytdlp_gui.ui.jobs_panel import JobsPanel

if TYPE_CHECKING:
    from ytdlp_gui.app import App


class MainWindow:
    def __init__(self, root: tk.Tk, app: "App"):
        self.root = root

        header = ttk.Frame(root, padding=(16, 12, 16, 0))
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, style="Heading.TLabel").pack(side="left")
        ttk.Button(header, text="Settings", command=app.open_settings).pack(side="right")
        ttk.Button(header, text="Tools & updates", command=app.open_tools).pack(side="right", padx=8)

        self.form = DownloadForm(root, app)
        self.form.pack(fill="x")

        status = ttk.Frame(root, padding=(16, 2, 16, 8))
        status.pack(side="bottom", fill="x")
        self.status_label = ttk.Label(status, style="Small.TLabel")
        self.status_label.pack(side="left")
        self.status_action = ttk.Button(status, style="Link.TButton")

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        self.jobs = JobsPanel(self.tabs, app)
        self.history = HistoryPanel(self.tabs, app)
        self.tabs.add(self.jobs, text="Downloads")
        self.tabs.add(self.history, text="History")

    def set_status(self, text: str, action_text: str = "", action: Optional[Callable[[], None]] = None) -> None:
        self.status_label.configure(text=text)
        if action_text and action:
            self.status_action.configure(text=action_text, command=action)
            self.status_action.pack(side="right")
        else:
            self.status_action.pack_forget()

    def show_downloads(self) -> None:
        self.tabs.select(self.jobs)
