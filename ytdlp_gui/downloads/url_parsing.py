"""
Finding links in pasted text and in .txt files.

Pasted text and files may contain one link per line, several links per line, blank lines
and comments. Lines starting with '#', ';' or ']' are comments (same rule as yt-dlp's
--batch-file). Links without "https://" (e.g. "youtu.be/abc") are accepted too.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_COMMENT_PREFIXES = ("#", ";", "]")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(r"^(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be|youtube-nocookie\.com)/\S+", re.IGNORECASE)


def extract_urls(text: str) -> list:
    """All links in `text`, in order, without duplicates."""
    urls: list = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(_COMMENT_PREFIXES):
            continue
        found = _URL_RE.findall(line)
        if not found:
            found = ["https://" + token for token in line.split() if _BARE_DOMAIN_RE.match(token)]
        for url in found:
            url = url.rstrip(".,;)")
            if url not in urls:
                urls.append(url)
    return urls


def read_url_file(path: Path) -> list:
    """Links from a text file (UTF-8, with or without BOM; bad bytes are ignored)."""
    return extract_urls(path.read_text(encoding="utf-8-sig", errors="replace"))


def url_kind(url: str) -> str:
    """Rough kind of a link, for labels only: 'short', 'playlist', 'video in playlist',
    'channel' or 'video'. yt-dlp itself decides what to download."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    if "/shorts/" in path:
        return "short"
    if path.startswith("/playlist") or ("list" in query and "v" not in query):
        return "playlist"
    if "list" in query and "v" in query:
        return "video in playlist"
    if path.startswith(("/@", "/channel/", "/c/", "/user/")):
        return "channel"
    return "video"
