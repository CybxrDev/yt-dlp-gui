"""
Progress maths for one job: % of the whole job, % of the current media, and time estimates.

A job is a list of links; each link can expand to many items (a playlist or channel); each
item may be downloaded as several parts (a video stream + an audio stream, merged later).

    job fraction   = (links done + current link fraction) / number of links
    link fraction  = (items done in link + current item fraction) / items in link
    item fraction  = bytes downloaded across all parts / expected bytes of all parts

Media ETA: bytes left / current speed (falls back to yt-dlp's own estimate).
Job ETA:   for a single item, the media ETA. Otherwise the elapsed time extrapolated from
           the job fraction, smoothed so the number doesn't jump around.
"""

from __future__ import annotations

import time
from typing import Optional

from ytdlp_gui.downloads.models import ItemStarted, PartProgress


class _Part:
    def __init__(self, part_id: str, expected: Optional[int]):
        self.part_id = part_id
        self.expected = expected  # size announced before downloading (may be approximate)
        self.reported: Optional[int] = None  # size reported while downloading (more accurate)
        self.downloaded = 0
        self.done = False

    @property
    def size(self) -> Optional[int]:
        return self.reported or self.expected

    @property
    def done_bytes(self) -> int:
        return (self.size or self.downloaded) if self.done else self.downloaded


class MediaProgress:
    """Progress of one item across all its parts."""

    def __init__(self, part_ids: list, part_sizes: list):
        self.parts = [_Part(pid, size or None) for pid, size in zip(part_ids, part_sizes)]
        self.speed: Optional[float] = None
        self._eta_hint: Optional[float] = None

    def update(self, event: PartProgress) -> None:
        part = self._part(event.part_id)
        index = self.parts.index(part)
        for earlier in self.parts[:index]:  # parts download one after another
            earlier.done = True
        part.downloaded = event.downloaded
        if event.total:
            part.reported = event.total
        if event.finished:
            part.done = True
        self.speed = event.speed
        self._eta_hint = event.eta

    def _part(self, part_id: str) -> _Part:
        for part in self.parts:
            if part.part_id == part_id:
                return part
        unstarted = [p for p in self.parts if not p.done and p.downloaded == 0 and not p.part_id]
        if unstarted:
            unstarted[0].part_id = part_id
            return unstarted[0]
        part = _Part(part_id, None)
        self.parts.append(part)
        return part

    def complete(self) -> None:
        for part in self.parts:
            part.done = True
        self.speed = None
        self._eta_hint = 0

    @property
    def downloaded_bytes(self) -> int:
        return sum(p.done_bytes for p in self.parts)

    @property
    def total_bytes(self) -> Optional[int]:
        sizes = [p.size for p in self.parts]
        return sum(sizes) if sizes and all(sizes) else None

    @property
    def fraction(self) -> float:
        if not self.parts:
            return 0.0
        total = self.total_bytes
        if total:
            return min(1.0, self.downloaded_bytes / total)
        # Sizes unknown: weigh each part equally.
        value = 0.0
        for part in self.parts:
            if part.done:
                value += 1
            elif part.size:
                value += min(1.0, part.downloaded / part.size)
        return value / len(self.parts)

    @property
    def eta(self) -> Optional[float]:
        total = self.total_bytes
        if total and self.speed:
            return max(0.0, (total - self.downloaded_bytes) / self.speed)
        return self._eta_hint


class JobProgressTracker:
    def __init__(self, link_count: int):
        self.link_count = max(1, link_count)
        self.link_index = 0
        self.items_in_link = 1
        self.items_done_in_link = 0
        self.item_position = 0
        self.media: Optional[MediaProgress] = None
        self.item_active = False
        self.started = time.monotonic()
        self._eta: Optional[float] = None
        self._eta_at = 0.0

    # --- events --------------------------------------------------------------------------

    def start_link(self, index: int) -> None:
        self.link_index = index
        self.items_in_link = 1
        self.items_done_in_link = 0
        self.item_position = 0
        self.media = None
        self.item_active = False

    def finish_link(self) -> None:
        self.items_done_in_link = self.items_in_link
        self.item_active = False

    def start_item(self, event: ItemStarted) -> None:
        if event.playlist_count:
            self.items_in_link = max(1, event.playlist_count)
        position = event.playlist_position or (self.item_position + 1)
        self.item_position = position
        self.items_in_link = max(self.items_in_link, position)
        self.items_done_in_link = max(self.items_done_in_link, position - 1)
        self.media = MediaProgress(event.part_ids, event.part_sizes)
        self.item_active = True

    def update_part(self, event: PartProgress) -> None:
        if self.media is None:
            self.media = MediaProgress([event.part_id], [None])
            self.item_active = True
        self.media.update(event)

    def finish_item(self) -> None:
        if self.media is not None:
            self.media.complete()
        if self.item_active:
            self.items_done_in_link = max(self.items_done_in_link + 1, self.item_position)
        self.items_done_in_link = min(self.items_done_in_link, self.items_in_link)
        self.item_active = False

    # --- derived values ------------------------------------------------------------------

    @property
    def media_fraction(self) -> float:
        return self.media.fraction if self.media else 0.0

    @property
    def job_fraction(self) -> float:
        current = self.media_fraction if self.item_active else 0.0
        link_fraction = min(1.0, (self.items_done_in_link + current) / self.items_in_link)
        return min(1.0, (self.link_index + link_fraction) / self.link_count)

    @property
    def media_eta(self) -> Optional[float]:
        return self.media.eta if self.media and self.item_active else None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def job_eta(self) -> Optional[float]:
        if self.link_count == 1 and self.items_in_link == 1:
            return self.media_eta
        now = time.monotonic()
        fraction = self.job_fraction
        elapsed = now - self.started
        if fraction < 0.005 or elapsed < 2:
            return None
        raw = elapsed * (1 - fraction) / fraction
        if self._eta is None:
            self._eta = raw
        else:
            decayed = max(0.0, self._eta - (now - self._eta_at))
            self._eta = 0.85 * decayed + 0.15 * raw
        self._eta_at = now
        return self._eta
