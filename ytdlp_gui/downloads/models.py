"""
Data passed between the download form, the queue, the engines and the UI.

Flow:  DownloadRequest  ->  DownloadQueue  ->  engine emits *events*  ->  ProgressTracker
       ->  JobSnapshot (what the UI shows)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


@dataclass
class DownloadRequest:
    """One "job": what the user asked for with a single click of Download / Import."""

    urls: list
    output_dir: str
    file_format: str  # key of format_selection.FORMAT_CHOICES
    resolution: str  # key of format_selection.RESOLUTION_CHOICES
    filename_pattern: str
    whole_playlist: bool
    label: str = ""  # shown until the first title is known (e.g. "links.txt – 12 links")


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"  # finished, but some items failed
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_finished(self) -> bool:
        return self not in (JobState.QUEUED, JobState.RUNNING)


# --------------------------------------------------------------------------------------
# Events emitted by an engine while it works (same events for both engines)
# --------------------------------------------------------------------------------------

@dataclass
class ItemStarted:
    """A single video/track is about to be downloaded."""

    video_id: str
    title: str
    url: str
    thumbnail_url: str
    playlist_position: Optional[int]  # 1-based position among the items being downloaded
    playlist_count: Optional[int]
    part_ids: list  # format ids downloaded for this item, e.g. ["137", "140"] (video + audio)
    part_sizes: list  # expected size in bytes of each part (None when unknown)
    expected_file: str = ""  # where the file will be saved (used to clean up after cancelling)


@dataclass
class PartProgress:
    """Progress of the part (video or audio stream) currently downloading."""

    part_id: str
    downloaded: int
    total: Optional[int]
    speed: Optional[float]  # bytes per second
    eta: Optional[float]  # seconds, as estimated by yt-dlp for this part
    finished: bool = False
    temp_file: str = ""


@dataclass
class PostProcessing:
    """FFmpeg work after downloading (merging, converting, embedding)."""

    step: str


@dataclass
class ItemFinished:
    file_path: str
    video_id: str
    title: str


@dataclass
class LogMessage:
    level: str  # "info", "warning" or "error"
    text: str


EngineEvent = Union[ItemStarted, PartProgress, PostProcessing, ItemFinished, LogMessage]


# --------------------------------------------------------------------------------------
# What the UI shows for a job
# --------------------------------------------------------------------------------------

@dataclass
class JobSnapshot:
    job_id: int
    state: JobState
    title: str
    stage: str  # e.g. "Downloading", "Merging video and audio", "Queued"
    output_dir: str
    description: str  # e.g. "MP4 · 1080p"
    link_number: int = 1  # 1-based number of the link being processed
    link_count: int = 1
    item_number: int = 0  # 1-based position of the current item within its link (playlist)
    item_count: int = 1  # number of items the current link expanded to
    job_fraction: float = 0.0
    job_eta: Optional[float] = None
    media_fraction: float = 0.0
    media_eta: Optional[float] = None
    speed: Optional[float] = None
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    video_id: str = ""
    thumbnail_url: str = ""
    last_file: str = ""
    files_done: int = 0
    error_count: int = 0
    last_error: str = ""
    elapsed: float = 0.0
    errors: list = field(default_factory=list)
