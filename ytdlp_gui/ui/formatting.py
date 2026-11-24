"""Turning numbers into short readable text (sizes, speeds, durations, dates)."""

from __future__ import annotations

import time
from typing import Optional


def format_bytes(value: Optional[float]) -> str:
    if value is None:
        return "?"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_speed(bytes_per_second: Optional[float]) -> str:
    return f"{format_bytes(bytes_per_second)}/s" if bytes_per_second else ""


def format_duration(seconds: Optional[float]) -> str:
    """'0:42', '12:05', '1:02:03' – or '--:--' when unknown."""
    if seconds is None or seconds < 0 or seconds != seconds:  # also rejects NaN
        return "--:--"
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_percent(fraction: float) -> str:
    return f"{max(0.0, min(1.0, fraction)) * 100:.0f}%"


def format_timestamp(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp)) if timestamp else ""


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"
