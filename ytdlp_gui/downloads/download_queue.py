"""
Runs download jobs on background threads and reports what happens.

Threading model
    * Each running job has one worker thread; at most `max_parallel_downloads` run at once
      and the rest wait in the queue (in the order they were added).
    * Workers never touch the UI. They call `notify(...)` with one of the notification
      classes below; the App forwards those to the UI thread.

Life of a job
    QUEUED -> RUNNING -> COMPLETED | PARTIAL (some items failed) | FAILED | CANCELLED
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ytdlp_gui.config.settings import Settings
from ytdlp_gui.downloads.engines import EngineContext, EngineError, create_engine
from ytdlp_gui.downloads.format_selection import describe
from ytdlp_gui.downloads.models import (
    DownloadRequest, EngineEvent, ItemFinished, ItemStarted, JobSnapshot, JobState, LogMessage,
    PartProgress, PostProcessing)
from ytdlp_gui.downloads.progress_tracker import JobProgressTracker
from ytdlp_gui.tools.tool_manager import ToolManager

log = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = 0.25  # seconds between progress updates sent to the UI per job
LOG_LINES_KEPT = 3000


# --- Notifications sent to the UI ------------------------------------------------------

@dataclass
class JobChanged:
    snapshot: JobSnapshot


@dataclass
class FileDownloaded:
    job_id: int
    request: DownloadRequest
    item: ItemFinished
    url: str
    thumbnail_url: str


@dataclass
class JobFinished:
    snapshot: JobSnapshot
    request: DownloadRequest


Notification = object  # one of JobChanged, FileDownloaded, JobFinished


class _Job:
    def __init__(self, job_id: int, request: DownloadRequest):
        self.id = job_id
        self.request = request
        self.state = JobState.QUEUED
        self.stage = "Waiting"
        self.cancel_event = threading.Event()
        self.tracker = JobProgressTracker(len(request.urls))
        self.log: deque = deque(maxlen=LOG_LINES_KEPT)
        self.errors: list = []
        self.files: list = []
        self.temp_files: set = set()
        self.title = request.label or (request.urls[0] if request.urls else "")
        self.video_id = ""
        self.thumbnail_url = ""
        self.item_url = ""
        self.last_sent = 0.0
        self.created_at = time.time()


class DownloadQueue:
    def __init__(self, get_settings: Callable[[], Settings], tools: ToolManager,
                 notify: Callable[[Notification], None]):
        self._settings = get_settings
        self._tools = tools
        self._notify = notify
        self._jobs: dict = {}
        self._lock = threading.RLock()
        self._next_id = 1

    # ----------------------------------------------------------------------------------
    # Public API (called from the UI thread)
    # ----------------------------------------------------------------------------------

    def add(self, request: DownloadRequest) -> int:
        with self._lock:
            job = _Job(self._next_id, request)
            self._next_id += 1
            self._jobs[job.id] = job
        self._send(job, force=True)
        self._start_waiting_jobs()
        return job.id

    def cancel(self, job_id: int) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state.is_finished:
                return
            job.cancel_event.set()
            if job.state is JobState.QUEUED:
                job.state = JobState.CANCELLED
                job.stage = "Cancelled"
                self._notify(JobFinished(self._snapshot(job), job.request))
            else:
                job.stage = "Cancelling…"
                self._send(job, force=True)

    def cancel_all(self) -> None:
        for job_id in list(self._jobs):
            self.cancel(job_id)

    def retry(self, job_id: int) -> int | None:
        job = self._jobs.get(job_id)
        return self.add(dataclasses.replace(job.request)) if job else None

    def forget(self, job_id: int) -> None:
        """Remove a finished job from the list."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.state.is_finished:
                del self._jobs[job_id]

    def finished_job_ids(self) -> list:
        with self._lock:
            return [j.id for j in self._jobs.values() if j.state.is_finished]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if not j.state.is_finished)

    def log_lines(self, job_id: int) -> list:
        job = self._jobs.get(job_id)
        return list(job.log) if job else []

    def request_of(self, job_id: int) -> DownloadRequest | None:
        job = self._jobs.get(job_id)
        return job.request if job else None

    # ----------------------------------------------------------------------------------
    # Scheduling
    # ----------------------------------------------------------------------------------

    def _start_waiting_jobs(self) -> None:
        with self._lock:
            limit = self._settings().max_parallel_downloads
            running = sum(1 for j in self._jobs.values() if j.state is JobState.RUNNING)
            for job in self._jobs.values():
                if running >= limit:
                    break
                if job.state is JobState.QUEUED:
                    job.state = JobState.RUNNING
                    job.stage = "Starting"
                    running += 1
                    threading.Thread(target=self._worker, args=(job,), name=f"job-{job.id}", daemon=True).start()

    def _worker(self, job: _Job) -> None:
        try:
            self._run(job)
        except EngineError as exc:
            self._record_error(job, str(exc))
        except Exception as exc:  # never let a worker die silently
            log.exception("Job %s crashed", job.id)
            self._record_error(job, f"Unexpected error: {exc}")
        finally:
            self._finish(job)
            self._start_waiting_jobs()

    def _run(self, job: _Job) -> None:
        settings = dataclasses.replace(self._settings())  # a copy: changes apply to the next job
        tools = self._tools.resolve()
        if tools.ffmpeg_dir is None:
            raise EngineError("FFmpeg is missing. It is needed to merge video and audio and to convert files. "
                              "Install it from Tools & updates (or set its location in Settings).")
        if tools.js_runtime is None:
            self._log(job, "warning", "No JavaScript runtime (Deno) found – YouTube downloads may fail or "
                                      "offer fewer formats. Install Deno from Tools & updates.")
        engine = create_engine(settings.engine)
        Path(job.request.output_dir).mkdir(parents=True, exist_ok=True)
        self._log(job, "info", f"Engine: {engine.display_name}; saving to {job.request.output_dir}")

        context = EngineContext(job.request, settings, tools, lambda event: self._on_event(job, event),
                                job.cancel_event)
        for index, url in enumerate(job.request.urls):
            if job.cancel_event.is_set():
                break
            job.tracker.start_link(index)
            job.stage = "Getting video information"
            self._log(job, "info", f"--- Link {index + 1} of {len(job.request.urls)}: {url}")
            self._send(job, force=True)
            if not engine.download(url, context) and not job.cancel_event.is_set():
                if not job.errors:
                    self._record_error(job, f"yt-dlp could not download {url} (see the log for details)")
            job.tracker.finish_link()

    def _finish(self, job: _Job) -> None:
        if job.cancel_event.is_set():
            job.state = JobState.CANCELLED
            job.stage = "Cancelled"
            self._remove_temp_files(job)
        elif job.errors:
            job.state = JobState.PARTIAL if job.files else JobState.FAILED
            job.stage = "Finished with errors" if job.files else "Failed"
        else:
            job.state = JobState.COMPLETED
            job.stage = "Done"
        self._log(job, "info", f"Job finished: {job.state.value}")
        self._notify(JobFinished(self._snapshot(job), job.request))

    # ----------------------------------------------------------------------------------
    # Engine events (called on the worker thread)
    # ----------------------------------------------------------------------------------

    def _on_event(self, job: _Job, event: EngineEvent) -> None:
        if isinstance(event, PartProgress):
            job.tracker.update_part(event)
            if event.temp_file:
                job.temp_files.add(event.temp_file)
            if not job.cancel_event.is_set():
                job.stage = "Downloading"
            self._send(job)
        elif isinstance(event, ItemStarted):
            job.tracker.start_item(event)
            if event.expected_file:
                job.temp_files.add(event.expected_file)
            job.title = event.title or job.title
            job.video_id = event.video_id
            job.thumbnail_url = event.thumbnail_url
            job.item_url = event.url
            job.stage = "Downloading"
            self._log(job, "info", f"Item: {event.title} [{event.video_id}] formats {'+'.join(event.part_ids)}")
            self._send(job, force=True)
        elif isinstance(event, PostProcessing):
            job.stage = event.step
            self._send(job, force=True)
        elif isinstance(event, ItemFinished):
            job.tracker.finish_item()
            if event.file_path:
                job.files.append(event.file_path)
            self._notify(FileDownloaded(job.id, job.request, event, job.item_url, job.thumbnail_url))
            self._send(job, force=True)
        elif isinstance(event, LogMessage):
            self._log(job, event.level, event.text)
            if event.level == "error":
                job.errors.append(event.text)
                self._send(job, force=True)

    # ----------------------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------------------

    def _log(self, job: _Job, level: str, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        prefix = "" if level == "info" else f"{level.upper()}: "
        job.log.append(f"{stamp}  {prefix}{text}")

    def _record_error(self, job: _Job, message: str) -> None:
        self._log(job, "error", message)
        job.errors.append(message)

    def _send(self, job: _Job, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - job.last_sent >= SNAPSHOT_INTERVAL:
            job.last_sent = now
            self._notify(JobChanged(self._snapshot(job)))

    def _snapshot(self, job: _Job) -> JobSnapshot:
        tracker = job.tracker
        media = tracker.media
        finished_ok = job.state in (JobState.COMPLETED, JobState.PARTIAL)
        return JobSnapshot(
            job_id=job.id,
            state=job.state,
            title=job.title,
            stage=job.stage,
            output_dir=job.request.output_dir,
            description=describe(job.request.file_format, job.request.resolution),
            link_number=tracker.link_index + 1,
            link_count=tracker.link_count,
            item_number=tracker.item_position,
            item_count=tracker.items_in_link,
            job_fraction=1.0 if finished_ok else tracker.job_fraction,
            job_eta=None if job.state.is_finished else tracker.job_eta(),
            media_fraction=1.0 if finished_ok else tracker.media_fraction,
            media_eta=None if job.state.is_finished else tracker.media_eta,
            speed=media.speed if media and tracker.item_active else None,
            downloaded_bytes=media.downloaded_bytes if media else 0,
            total_bytes=media.total_bytes if media else None,
            video_id=job.video_id,
            thumbnail_url=job.thumbnail_url,
            last_file=job.files[-1] if job.files else "",
            files_done=len(job.files),
            error_count=len(job.errors),
            last_error=job.errors[-1] if job.errors else "",
            elapsed=tracker.elapsed,
            errors=list(job.errors),
        )

    @staticmethod
    def _remove_temp_files(job: _Job) -> None:
        """Delete partial downloads left behind by a cancelled job.

        Only yt-dlp's intermediate files are touched (".part", ".ytdl", and per-stream files
        like "Title.f137.mp4"), and only ones written since this job started - never a
        finished file or anything that was already on disk."""
        finished = {os.path.abspath(f) for f in job.files}
        for temp in job.temp_files:
            # The cover image yt-dlp saved for embedding shares the media file's base name.
            base = _MEDIA_SUFFIX.sub("", temp)
            thumbnails = [base + ext for ext in (".jpg", ".webp", ".png")]
            for candidate in (temp, temp + ".part", temp + ".ytdl", *thumbnails):
                path = os.path.abspath(candidate)
                is_thumbnail = candidate in thumbnails
                if path in finished or not os.path.isfile(path):
                    continue
                if not is_thumbnail and not _INTERMEDIATE_FILE.search(path):
                    continue
                try:
                    if os.path.getmtime(path) >= job.created_at - 2:
                        os.remove(path)
                except OSError:
                    pass


# yt-dlp's temporary/intermediate file names, and the suffix to strip to get the base name
_FORMAT_ID = r"\.f(?:\d|hls|dash|http)[\w-]*"  # e.g. ".f137", ".fhls-1080p"
_INTERMEDIATE_FILE = re.compile(rf"(\.part|\.ytdl|\.part-Frag\d+|{_FORMAT_ID}\.\w+(\.part)?)$")
_MEDIA_SUFFIX = re.compile(rf"({_FORMAT_ID})?\.\w+(\.part)?$")
