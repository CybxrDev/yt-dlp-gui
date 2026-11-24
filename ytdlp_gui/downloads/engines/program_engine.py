"""
Engine that runs the yt-dlp program (a separate executable) and reads its output.

This keeps downloads working independently of the Python code inside the app: point it at
any yt-dlp executable (app-managed, system-wide, or your own) in Settings.

yt-dlp is asked to print machine-readable lines, each starting with MARKER, alongside its
normal output:

    MARKER ITEM {json}           before an item downloads (title, playlist position, ...)
    MARKER PARTS [json]          the streams of that item and their expected sizes
    MARKER PROG "id" {json}      download progress of the current stream
    MARKER PP started Merger     an FFmpeg post-processing step
    MARKER DONE {json}           the final file is in place

Other lines are logged; lines starting with ERROR:/WARNING: are reported as such.
Cancelling kills the yt-dlp process together with any FFmpeg it started.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading

from ytdlp_gui.downloads.engines.base import (
    DownloadEngine, EngineContext, EngineError, clean_message, postprocessor_label, youtube_thumbnail)
from ytdlp_gui.downloads.models import ItemFinished, ItemStarted, LogMessage, PartProgress, PostProcessing
from ytdlp_gui.downloads.ytdlp_arguments import build_arguments
from ytdlp_gui.tools.platform_info import IS_WINDOWS, hidden_process_kwargs

MARKER = "@@ytdlp-gui@@"

_ITEM_FIELDS = ("id,title,webpage_url,original_url,thumbnail,extractor_key,playlist_index,"
                "playlist_autonumber,n_entries,playlist_count,format_id,filesize,filesize_approx,filename")

REPORTING_ARGUMENTS = [
    "--newline",  # one progress line per update instead of redrawing a single line
    "--progress",  # keep progress output although --print makes yt-dlp quiet
    "--no-simulate",  # --print would otherwise only simulate
    "--progress-delta", "0.5",
    "--encoding", "utf-8",
    "--print", f"before_dl:{MARKER} ITEM %(.{{{_ITEM_FIELDS}}})j",
    "--print", f"before_dl:{MARKER} PARTS %(requested_formats.:.{{format_id,filesize,filesize_approx}})j",
    "--print", f"after_move:{MARKER} DONE %(.{{id,title,filepath}})j",
    "--progress-template", f"download:{MARKER} PROG %(info.format_id)j %(progress)j",
    "--progress-template", f"postprocess:{MARKER} PP %(progress.status)s %(progress.postprocessor)s",
]


class ProgramEngine(DownloadEngine):
    display_name = "yt-dlp program"

    def download(self, url: str, ctx: EngineContext) -> bool:
        program = ctx.tools.ytdlp_program
        if program is None:
            raise EngineError("The yt-dlp program wasn't found. Install it from Tools & updates, "
                              "or choose where it is in Settings → Engine & tools.")
        command = [str(program), *build_arguments(ctx.request, ctx.settings, ctx.tools),
                   *REPORTING_ARGUMENTS, "--", url]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1"}
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env, start_new_session=not IS_WINDOWS, **hidden_process_kwargs())
        except OSError as exc:
            raise EngineError(f"Could not start yt-dlp ({program}): {exc}") from exc

        watcher = threading.Thread(target=_stop_when_cancelled, args=(process, ctx.cancel_event), daemon=True)
        watcher.start()
        parser = _OutputParser(ctx)
        for raw_line in process.stdout:
            for line in raw_line.decode("utf-8", "replace").split("\r"):
                parser.feed(line.strip())
        parser.flush()
        return_code = process.wait()
        if ctx.cancel_event.is_set():
            return False
        return return_code == 0 and not parser.had_error


def _stop_when_cancelled(process: subprocess.Popen, cancel_event: threading.Event) -> None:
    while process.poll() is None:
        if cancel_event.wait(0.3):
            _kill_process_tree(process)
            return


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Stop yt-dlp and the FFmpeg/Deno processes it started."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_process_kwargs())
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(5)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)


class _OutputParser:
    """Turns yt-dlp output lines into engine events."""

    def __init__(self, ctx: EngineContext):
        self._ctx = ctx
        self._pending_item: dict | None = None  # ITEM line waiting for its PARTS line
        self.had_error = False

    def feed(self, line: str) -> None:
        if not line:
            return
        if not line.startswith(MARKER):
            self._log_line(line)
            return
        kind, _, payload = line[len(MARKER):].strip().partition(" ")
        try:
            if kind == "ITEM":
                self.flush()
                self._pending_item = json.loads(payload)
                return
            if kind == "PARTS":
                self._emit_item(_parse_parts(payload))
                return
            self.flush()
            if kind == "PROG":
                self._on_progress(payload)
            elif kind == "PP":
                status, _, name = payload.partition(" ")
                label = postprocessor_label(name.strip())
                if status == "started" and label:
                    self._ctx.emit(PostProcessing(label))
            elif kind == "DONE":
                info = json.loads(payload)
                self._ctx.emit(ItemFinished(info.get("filepath") or "", str(info.get("id") or ""),
                                            info.get("title") or ""))
        except (ValueError, TypeError, AttributeError):
            self._ctx.emit(LogMessage("info", line))

    def flush(self) -> None:
        """Emit an ITEM whose PARTS line never came (e.g. a single-stream download)."""
        if self._pending_item is not None:
            self._emit_item(None)

    def _emit_item(self, parts: list | None) -> None:
        info, self._pending_item = self._pending_item or {}, None
        if not info:
            return
        if not parts:  # single stream: use the item's own format id and size
            ids = str(info.get("format_id") or "").split("+")
            size = info.get("filesize") or info.get("filesize_approx")
            parts = [{"format_id": i, "filesize": size if len(ids) == 1 else None} for i in ids]
        video_id = str(info.get("id") or "")
        self._ctx.emit(ItemStarted(
            video_id=video_id,
            title=info.get("title") or video_id,
            url=info.get("webpage_url") or info.get("original_url") or "",
            thumbnail_url=youtube_thumbnail(info.get("thumbnail") or "", video_id, info.get("extractor_key") or ""),
            playlist_position=info.get("playlist_autonumber") or info.get("playlist_index"),
            playlist_count=info.get("n_entries") or info.get("playlist_count"),
            part_ids=[str(p.get("format_id") or "") for p in parts],
            part_sizes=[p.get("filesize") or p.get("filesize_approx") for p in parts],
            expected_file=info.get("filename") or "",
        ))

    def _on_progress(self, payload: str) -> None:
        format_id_json, _, progress_json = payload.partition(" ")
        part_id = json.loads(format_id_json) if format_id_json not in ("NA", "") else ""
        progress = json.loads(progress_json)
        state = progress.get("status")
        if state not in ("downloading", "finished"):
            return
        total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
        self._ctx.emit(PartProgress(
            part_id=str(part_id or ""),
            downloaded=int(progress.get("downloaded_bytes") or 0),
            total=int(total) if total else None,
            speed=progress.get("speed"),
            eta=progress.get("eta"),
            finished=state == "finished",
            temp_file=progress.get("tmpfilename") or progress.get("filename") or "",
        ))

    def _log_line(self, line: str) -> None:
        if line.startswith("ERROR:"):
            self.had_error = True
            self._ctx.emit(LogMessage("error", clean_message(line)))
        elif line.startswith("WARNING:"):
            self._ctx.emit(LogMessage("warning", clean_message(line)))
        else:
            self._ctx.emit(LogMessage("info", line))


def _parse_parts(payload: str) -> list | None:
    try:
        parts = json.loads(payload)
    except ValueError:
        return None  # yt-dlp prints "NA" when the item has a single stream
    return [p for p in parts if isinstance(p, dict)] if isinstance(parts, list) else None
