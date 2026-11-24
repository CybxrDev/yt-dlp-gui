"""
File-name patterns: the friendly "[title] - [id]" syntax -> a yt-dlp output template.

    "[title] - [id]"                  ->  "%(title)s - %(id)s.%(ext)s"
    "[playlist]/[index] - [title]"    ->  sub-folder per playlist

Rules:
  * Tokens are words in square brackets (see TOKENS). Unknown ones stay as typed, so
    "[1080p] [title]" gives "[1080p] My video.mp4".
  * The extension is always added from the chosen format; a typed ".mp4" is removed.
  * Native yt-dlp fields like %(uploader)s also work, for advanced use.
  * "/" creates sub-folders inside the download folder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_PATTERN = "[title] - [id]"


@dataclass(frozen=True)
class Token:
    template: str  # yt-dlp output template snippet
    description: str
    sample: str  # used for the live preview in the download form


TOKENS = {
    "title": Token("%(title)s", "Video title", "My video"),
    "id": Token("%(id)s", "Video ID", "dQw4w9WgXcQ"),
    "url_id": Token("%(id)s", "Video ID (same as [id])", "dQw4w9WgXcQ"),
    "channel": Token("%(channel,uploader)s", "Channel name", "Some Channel"),
    "uploader": Token("%(uploader)s", "Uploader name", "Some Channel"),
    "upload_date": Token("%(upload_date>%Y-%m-%d)s", "Upload date (YYYY-MM-DD)", "2024-05-01"),
    "download_date": Token("%(epoch>%Y-%m-%d)s", "Download date (YYYY-MM-DD)", "2026-01-31"),
    "resolution": Token("%(height&{}p|audio)s", "Video height, e.g. 1080p", "1080p"),
    "duration": Token("%(duration_string)s", "Length, e.g. 3:45", "3-45"),
    "playlist": Token("%(playlist_title|)s", "Playlist name (empty if none)", "My playlist"),
    "index": Token("%(playlist_index|)s", "Position in the playlist (empty if none)", "01"),
    "ext": Token("%(ext)s", "File extension", "mp4"),
}

# One alternative per kind of piece: a native %(field)x template, a [token], or a lone '%'.
_PIECES = re.compile(r"(%\([^)]*\)[-#0+ ]*\d*(?:\.\d+)?[a-zA-Z])|\[(\w+)\]|(%)")
_TRAILING_EXT = re.compile(
    r"\.(?:%\(ext\)s|\[ext\]|mp4|mkv|webm|mp3|m4a|opus|flac|wav|mov|avi)\s*$", re.IGNORECASE)


def _clean(pattern: str) -> str:
    pattern = pattern.strip() or DEFAULT_PATTERN
    return _TRAILING_EXT.sub("", pattern).strip() or DEFAULT_PATTERN


def to_output_template(pattern: str) -> str:
    """yt-dlp output template for a pattern (extension added automatically)."""

    def replace(match: re.Match) -> str:
        native, token, percent = match.groups()
        if native:
            return native
        if token is not None:
            known = TOKENS.get(token.lower())
            return known.template if known else match.group(0)
        return "%%"  # a literal % must be doubled in yt-dlp templates

    return _PIECES.sub(replace, _clean(pattern)) + ".%(ext)s"


def preview(pattern: str, extension: str) -> str:
    """Example file name for the pattern, for showing under the input box."""

    def replace(match: re.Match) -> str:
        native, token, percent = match.groups()
        if native:
            return "…"
        if token is not None:
            known = TOKENS.get(token.lower())
            return known.sample if known else match.group(0)
        return "%"

    return _PIECES.sub(replace, _clean(pattern)) + "." + extension
