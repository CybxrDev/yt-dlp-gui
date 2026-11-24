"""A window showing one job's detailed log (what yt-dlp printed), for troubleshooting."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ytdlp_gui.app import App


class LogWindow(tk.Toplevel):
    REFRESH_MS = 1000

    def __init__(self, app: "App", job_id: int, title: str):
        super().__init__(app.root)
        self.app = app
        self.job_id = job_id
        self.title(f"Log – {title}")
        self.geometry("820x460")
        self.configure(background=app.theme.palette.bg)
        self._shown = 0

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="word", font=app.theme.fonts["mono"], borderwidth=0,
                            highlightthickness=1, padx=6, pady=6)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        app.theme.style_text_widget(self.text)
        palette = app.theme.palette
        self.text.tag_configure("error", foreground=palette.danger)
        self.text.tag_configure("warning", foreground=palette.warning)

        buttons = ttk.Frame(self, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Copy all", command=self._copy).pack(side="right", padx=6)
        self._refresh()

    def _refresh(self) -> None:
        if not self.winfo_exists():
            return
        lines = self.app.queue.log_lines(self.job_id)
        if len(lines) < self._shown:  # older lines were dropped; redraw everything
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self._shown = 0
        new = lines[self._shown:]
        if new:
            at_bottom = self.text.yview()[1] > 0.98
            self.text.configure(state="normal")
            for line in new:
                tag = "error" if "ERROR:" in line else "warning" if "WARNING:" in line else ""
                self.text.insert("end", line + "\n", tag)
            self.text.configure(state="disabled")
            if at_bottom or self._shown == 0:
                self.text.see("end")
            self._shown = len(lines)
        self.after(self.REFRESH_MS, self._refresh)

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.app.queue.log_lines(self.job_id)))
