"""Common interface of the download engines, plus helpers they share."""

from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from ytdlp_gui.config.settings import Settings
from ytdlp_gui.downloads.models import DownloadRequest, EngineEvent
from ytdlp_gui.tools.tool_manager import ResolvedTools

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# yt-dlp post-processor names -> what the user sees while it runs.
_POSTPROCESSOR_LABELS = {
    "Merger": "Merging video and audio",
    "VideoRemuxer": "Repackaging video",
    "VideoConvertor": "Converting video",
    "ExtractAudio": "Converting audio",
    "EmbedThumbnail": "Embedding thumbnail",
    "ThumbnailsConvertor": "Preparing thumbnail",
    "Metadata": "Adding metadata",
    "FixupM4a": "Fixing file",
    "FixupM3u8": "Fixing file",
    "FixupStretched": "Fixing file",
    "FixupDuplicateMoov": "Fixing file",
    "FixupTimestamp": "Fixing file",
    "FixupDuration": "Fixing file",
}
# Internal post-processors that aren't worth showing (names starting with "_" are this app's own).
_HIDDEN_POSTPROCESSORS = {"MoveFiles", "MoveFilesAfterDownload", "Exec", "SponsorBlock", ""}


class EngineError(Exception):
    """Something that prevents a download from starting, explained for the user."""


@dataclass
class EngineContext:
    request: DownloadRequest
    settings: Settings
    tools: ResolvedTools
    emit: Callable[[EngineEvent], None]
    cancel_event: threading.Event


class DownloadEngine(ABC):
    display_name = "engine"

    @abstractmethod
    def download(self, url: str, ctx: EngineContext) -> bool:
        """Download one link (a video, a playlist or a channel).

        Report progress through ctx.emit, stop soon after ctx.cancel_event is set, and
        return True only if everything for this link succeeded."""


def clean_message(text: str) -> str:
    """Remove colour codes and the "ERROR:"/"WARNING:" prefix yt-dlp adds."""
    text = _ANSI_ESCAPE.sub("", text).strip()
    for prefix in ("ERROR:", "WARNING:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def postprocessor_label(name: str) -> str | None:
    if name in _HIDDEN_POSTPROCESSORS or name.startswith("_"):
        return None
    return _POSTPROCESSOR_LABELS.get(name, f"Processing ({name})")


def youtube_thumbnail(url: str, video_id: str, extractor: str = "") -> str:
    """Prefer YouTube's small fixed-size thumbnail (fast to fetch); otherwise keep `url`."""
    if video_id and (extractor.lower().startswith("youtube") or "ytimg.com" in url):
        return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
    return url
