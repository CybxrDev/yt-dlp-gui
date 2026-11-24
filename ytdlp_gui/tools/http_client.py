"""
Minimal HTTP helpers built on the standard library (urllib), used for update checks and
tool downloads. yt-dlp itself does its own networking; this is only for the app's needs.

Uses the certifi certificate bundle when available, because compiled apps (especially on
macOS) often can't find the system certificates.
"""

from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from ytdlp_gui import APP_ID, APP_VERSION

USER_AGENT = f"{APP_ID}/{APP_VERSION}"
TIMEOUT = 30
CHUNK_SIZE = 256 * 1024

# progress(downloaded_bytes, total_bytes_or_None)
ProgressCallback = Callable[[int, "int | None"], None]


class DownloadCancelled(Exception):
    pass


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL = _ssl_context()


def _request(url: str, accept: str | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def get_json(url: str) -> object:
    accept = "application/vnd.github+json" if "api.github.com" in url else "application/json"
    with urllib.request.urlopen(_request(url, accept), timeout=TIMEOUT, context=_SSL) as resp:
        return json.load(resp)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib API
        return None


def redirect_target(url: str) -> str:
    """Where `url` redirects to (without following it). Used to learn the latest version
    from GitHub's ".../releases/latest" link without using the rate-limited API."""
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_SSL))
    for attempt in range(3):
        try:
            with opener.open(_request(url), timeout=TIMEOUT) as resp:
                return resp.geturl()  # no redirect happened
        except urllib.error.HTTPError as err:
            if err.code in (301, 302, 303, 307, 308) and err.headers.get("Location"):
                return urllib.request.urljoin(url, err.headers["Location"])
            if attempt == 2 or err.code not in (404, 429, 500, 502, 503):
                raise
        time.sleep(1.5)
    raise RuntimeError(f"Could not resolve {url}")


def download_file(
    url: str,
    destination: Path,
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download to `destination` (via a .part file, renamed when complete)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=_SSL) as resp:
        total = int(resp.headers.get("Content-Length") or 0) or None
        done = 0
        last_report = 0.0
        with open(partial, "wb") as out:
            while True:
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if progress and now - last_report > 0.1:
                    last_report = now
                    progress(done, total)
    if total and done < total:
        partial.unlink(missing_ok=True)
        raise IOError(f"Download incomplete ({done} of {total} bytes)")
    if progress:
        progress(done, total)
    partial.replace(destination)
    return destination
