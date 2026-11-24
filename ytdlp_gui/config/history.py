"""
Download history shown in the History tab.

One entry per downloaded file (each video of a playlist gets its own entry), plus one
entry for each link that failed completely. Stored as JSON, newest first. Recording can be
turned off in Settings; entries can be removed individually or all at once.

Only used from the UI thread, so no locking is needed.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

MAX_ENTRIES = 5000


@dataclass
class HistoryEntry:
    title: str
    url: str
    file_path: str = ""
    video_id: str = ""
    thumbnail_url: str = ""
    file_format: str = ""
    resolution: str = ""
    status: str = "completed"  # "completed" or "failed"
    error: str = ""
    finished_at: float = 0.0  # unix timestamp
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class HistoryStore:
    def __init__(self, path: Path):
        self._path = path
        self._entries: list[HistoryEntry] = self._load()

    @property
    def entries(self) -> list[HistoryEntry]:
        """Newest first. Returns a copy, so callers can't modify the store by accident."""
        return list(self._entries)

    def add(self, entry: HistoryEntry) -> None:
        self._entries.insert(0, entry)
        del self._entries[MAX_ENTRIES:]
        self._save()

    def remove(self, entry_ids: set[str]) -> list[HistoryEntry]:
        removed = [e for e in self._entries if e.entry_id in entry_ids]
        self._entries = [e for e in self._entries if e.entry_id not in entry_ids]
        self._save()
        return removed

    def clear(self) -> None:
        self._entries = []
        self._save()

    # --- storage ---------------------------------------------------------------------

    def _load(self) -> list[HistoryEntry]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            log.warning("Could not read history (%s); starting empty", exc)
            return []
        known = {f.name for f in fields(HistoryEntry)}
        entries = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict) and "title" in item and "url" in item:
                try:
                    entries.append(HistoryEntry(**{k: v for k, v in item.items() if k in known}))
                except TypeError:
                    continue
        return entries

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps([asdict(e) for e in self._entries], indent=1), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            log.error("Could not save history: %s", exc)
