"""
The "Downloads" tab: one card per job, newest at the top.

Each card shows the thumbnail and title of the item being downloaded, a status line, and
two progress bars with time estimates:
    This file   progress of the current video/track (video + audio streams combined)
    Whole job   progress of everything the job contains (all links / playlist items)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from ytdlp_gui.downloads.models import JobSnapshot, JobState
from ytdlp_gui.ui.formatting import format_bytes, format_duration, format_percent, format_speed, shorten
from ytdlp_gui.ui.log_window import LogWindow
from ytdlp_gui.ui.widgets import ScrollableFrame, open_path, reveal_in_folder

if TYPE_CHECKING:
    from ytdlp_gui.app import App

_STATE_LABELS = {
    JobState.QUEUED: "Queued",
    JobState.COMPLETED: "Done",
    JobState.PARTIAL: "Done with errors",
    JobState.FAILED: "Failed",
    JobState.CANCELLED: "Cancelled",
}


class JobsPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "App"):
        super().__init__(master)
        self.app = app
        self.rows: dict = {}

        toolbar = ttk.Frame(self, padding=(12, 8, 12, 4))
        toolbar.pack(fill="x")
        self.summary_var = tk.StringVar()
        ttk.Label(toolbar, textvariable=self.summary_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(toolbar, text="Clear finished", command=self._clear_finished).pack(side="right")
        ttk.Button(toolbar, text="Cancel all", command=self.app.queue.cancel_all).pack(side="right", padx=6)

        self.scroll = ScrollableFrame(self, app.theme)
        self.scroll.pack(fill="both", expand=True, padx=(12, 0), pady=(0, 8))
        self.empty_label = ttk.Label(self.scroll.inner, style="Muted.TLabel", justify="center",
                                     text="No downloads yet.\nPaste a link above and press Download.")
        self._refresh()

    def show(self, snapshot: JobSnapshot) -> None:
        row = self.rows.get(snapshot.job_id)
        if row is None:
            row = JobRow(self.scroll.inner, self, snapshot.job_id)
            existing = [w for w in self.scroll.inner.pack_slaves() if isinstance(w, JobRow)]
            if existing:  # newest job goes on top
                row.pack(fill="x", pady=(0, 8), padx=(0, 12), before=existing[0])
            else:
                row.pack(fill="x", pady=(0, 8), padx=(0, 12))
            self.rows[snapshot.job_id] = row
        row.update_from(snapshot)
        self._refresh()

    def remove(self, job_id: int) -> None:
        self.app.queue.forget(job_id)
        row = self.rows.pop(job_id, None)
        if row is not None:
            row.destroy()
        self._refresh()

    def _clear_finished(self) -> None:
        for job_id in self.app.queue.finished_job_ids():
            self.remove(job_id)

    def _refresh(self) -> None:
        if self.rows:
            self.empty_label.pack_forget()
        else:
            self.empty_label.pack(pady=40)
        states = [row.state for row in self.rows.values()]
        running = sum(1 for s in states if s is JobState.RUNNING)
        queued = sum(1 for s in states if s is JobState.QUEUED)
        finished = len(states) - running - queued
        parts = []
        if running:
            parts.append(f"{running} downloading")
        if queued:
            parts.append(f"{queued} waiting")
        if finished:
            parts.append(f"{finished} finished")
        self.summary_var.set(" · ".join(parts))


class JobRow(ttk.Frame):
    """One job card."""

    def __init__(self, master: tk.Misc, panel: JobsPanel, job_id: int):
        super().__init__(master, style="Card.TFrame", padding=(10, 10))
        self.panel = panel
        self.app = panel.app
        self.job_id = job_id
        self.state: JobState | None = None
        self.snapshot: JobSnapshot | None = None
        self._thumb_key = ""
        self._button_state: str | None = None
        self.columnconfigure(1, weight=1)

        self.thumb = ttk.Label(self, style="Card.TLabel", image=self.app.thumbnails.placeholder())
        self.thumb.grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, 12))
        # width=1: long text is clipped at the card's edge instead of widening the card
        self.title = ttk.Label(self, style="CardTitle.TLabel", anchor="w", width=1)
        self.title.grid(row=0, column=1, sticky="ew")
        self.status = ttk.Label(self, style="CardMuted.TLabel", anchor="w", width=1)
        self.status.grid(row=1, column=1, sticky="ew", pady=(2, 4))
        self.buttons = ttk.Frame(self, style="CardPlain.TFrame")
        self.buttons.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(8, 0))

        self.media_bar, self.media_text = self._progress_line(2, "This file", "Horizontal.TProgressbar")
        self.job_bar, self.job_text = self._progress_line(3, "Whole job", "Job.Horizontal.TProgressbar")
        self.error = ttk.Label(self, style="CardError.TLabel", anchor="w", wraplength=600, justify="left")
        self.bind("<Configure>", lambda e: self.error.configure(wraplength=max(200, e.width - 140)))

    def _progress_line(self, row: int, label: str, style: str):
        line = ttk.Frame(self, style="CardPlain.TFrame")
        line.grid(row=row, column=1, columnspan=2, sticky="ew", pady=1)
        line.columnconfigure(1, weight=1)
        ttk.Label(line, text=label, style="CardMuted.TLabel", width=10).grid(row=0, column=0, sticky="w")
        bar = ttk.Progressbar(line, style=style, maximum=1000, mode="determinate")
        bar.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        text = ttk.Label(line, style="CardMuted.TLabel", width=44, anchor="w")
        text.grid(row=0, column=2, sticky="w")
        return bar, text

    # ----------------------------------------------------------------------------------

    def update_from(self, s: JobSnapshot) -> None:
        self.snapshot = s
        self.state = s.state
        self.title.configure(text=shorten(s.title or "…", 110))
        self.status.configure(text=self._status_text(s))
        self.media_bar["value"] = s.media_fraction * 1000
        self.job_bar["value"] = s.job_fraction * 1000
        self.media_text.configure(text=self._media_text(s))
        self.job_text.configure(text=self._job_text(s))

        if s.error_count:
            more = f"  (+{s.error_count - 1} more – see Log)" if s.error_count > 1 else ""
            self.error.configure(text=shorten(s.last_error, 300) + more)
            self.error.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(4, 0))
        else:
            self.error.grid_forget()

        key = s.video_id or ""
        if key and key != self._thumb_key and s.thumbnail_url:
            self._thumb_key = key
            self.app.thumbnails.request(key, s.thumbnail_url, self._set_thumbnail)
        self._update_buttons(s)

    def _set_thumbnail(self, image: tk.PhotoImage) -> None:
        if self.winfo_exists():
            self.thumb.configure(image=image)

    @staticmethod
    def _status_text(s: JobSnapshot) -> str:
        stage = s.stage if s.state is JobState.RUNNING else _STATE_LABELS.get(s.state, s.stage)
        parts = [stage, s.description]
        if s.link_count > 1:
            parts.append(f"link {s.link_number} of {s.link_count}")
        if s.item_count > 1 and s.state is JobState.RUNNING:
            parts.append(f"item {s.item_number} of {s.item_count}")
        if s.state.is_finished and s.files_done:
            parts.append(f"{s.files_done} file{'s' if s.files_done != 1 else ''}")
        if s.state.is_finished and s.elapsed and s.state is not JobState.CANCELLED:
            parts.append(f"took {format_duration(s.elapsed)}")
        return "  ·  ".join(p for p in parts if p)

    @staticmethod
    def _media_text(s: JobSnapshot) -> str:
        if s.state is JobState.QUEUED:
            return "waiting"
        if s.state.is_finished:
            return format_percent(s.media_fraction)
        parts = [format_percent(s.media_fraction)]
        if s.total_bytes:
            parts.append(f"{format_bytes(s.downloaded_bytes)} of {format_bytes(s.total_bytes)}")
        if s.speed:
            parts.append(format_speed(s.speed))
        if s.media_eta is not None:
            parts.append(f"{format_duration(s.media_eta)} left")
        return "  ·  ".join(parts)

    @staticmethod
    def _job_text(s: JobSnapshot) -> str:
        if s.state is JobState.QUEUED:
            return "waiting"
        text = format_percent(s.job_fraction)
        if not s.state.is_finished:
            text += f"  ·  {format_duration(s.job_eta)} left" if s.job_eta is not None else "  ·  estimating…"
        return text

    def _update_buttons(self, s: JobSnapshot) -> None:
        key = f"{s.state.is_finished}-{bool(s.files_done)}-{s.state.value}"
        if key == self._button_state:
            return
        self._button_state = key
        for child in self.buttons.winfo_children():
            child.destroy()

        def add(text: str, command) -> None:
            ttk.Button(self.buttons, text=text, style="Card.TButton", command=command).pack(side="left", padx=(4, 0))

        if not s.state.is_finished:
            add("Cancel", lambda: self.app.queue.cancel(self.job_id))
        else:
            if s.files_done == 1 and s.last_file:
                add("Open", lambda: open_path(self.snapshot.last_file))
            if s.files_done:
                add("Folder", self._show_folder)
            if s.state in (JobState.FAILED, JobState.PARTIAL, JobState.CANCELLED):
                add("Retry", self._retry)
        add("Log", lambda: LogWindow(self.app, self.job_id, self.title.cget("text")))
        if s.state.is_finished:
            add("✕", lambda: self.panel.remove(self.job_id))

    def _show_folder(self) -> None:
        if self.snapshot and self.snapshot.last_file:
            reveal_in_folder(self.snapshot.last_file)
        elif self.snapshot:
            open_path(self.snapshot.output_dir)

    def _retry(self) -> None:
        request = self.app.queue.request_of(self.job_id)
        if request is not None:
            self.panel.remove(self.job_id)
            self.app.start_downloads([request])
