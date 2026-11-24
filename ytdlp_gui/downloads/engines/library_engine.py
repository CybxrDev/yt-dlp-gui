"""
Engine that runs yt-dlp as a Python library inside this process (the default).

How information gets out of yt-dlp:
    progress_hooks              bytes downloaded for the current stream  -> PartProgress
    postprocessor_hooks         FFmpeg steps such as merging             -> PostProcessing
    post-processor "before_dl"  title, playlist position, stream sizes   -> ItemStarted
    post-processor "after_move" final file path                          -> ItemFinished
    logger                      log lines, warnings and errors           -> LogMessage

Cancelling: while a download runs, the hooks and logger raise yt-dlp's own
DownloadCancelled exception once the job's cancel flag is set; yt-dlp unwinds cleanly.
"""

from __future__ import annotations

from ytdlp_gui.downloads.engines.base import (
    DownloadEngine, EngineContext, EngineError, clean_message, postprocessor_label, youtube_thumbnail)
from ytdlp_gui.downloads.models import ItemFinished, ItemStarted, LogMessage, PartProgress, PostProcessing
from ytdlp_gui.downloads.ytdlp_arguments import build_arguments
from ytdlp_gui.tools import ytdlp_library_loader


class LibraryEngine(DownloadEngine):
    display_name = "yt-dlp library"

    def download(self, url: str, ctx: EngineContext) -> bool:
        try:
            yt_dlp = ytdlp_library_loader.import_ytdlp()
        except ImportError as exc:
            raise EngineError("The yt-dlp library isn't installed. Install it from Tools & updates, "
                              "or switch to the program engine in Settings.") from exc
        from yt_dlp.postprocessor.common import PostProcessor
        from yt_dlp.utils import DownloadCancelled, DownloadError

        # Same arguments as the program engine, converted by yt-dlp's own option parser.
        arguments = build_arguments(ctx.request, ctx.settings, ctx.tools)
        try:
            ydl_options = yt_dlp.parse_options(arguments).ydl_opts
        except SystemExit as exc:  # the option parser exits on invalid options
            raise EngineError(f"yt-dlp rejected the download options (code {exc.code}).") from exc

        reporter = _Reporter(ctx, DownloadCancelled)
        ydl_options.update(
            logger=reporter,
            progress_hooks=[reporter.on_download_progress],
            postprocessor_hooks=[reporter.on_postprocessor],
            noprogress=True,
        )
        try:
            with yt_dlp.YoutubeDL(ydl_options) as ydl:
                ydl.add_post_processor(_callback_postprocessor(PostProcessor, reporter.on_item_started), when="before_dl")
                ydl.add_post_processor(_callback_postprocessor(PostProcessor, reporter.on_item_finished), when="after_move")
                reporter.active = True
                try:
                    return_code = ydl.download([url])
                finally:
                    reporter.active = False
        except DownloadCancelled:
            return False
        except DownloadError:
            return False  # the reason was already reported through the logger
        return return_code == 0 and not reporter.had_error


def _callback_postprocessor(base_class, callback):
    """A yt-dlp post-processor that only calls `callback(info)` at its stage."""

    class _CallbackPP(base_class):
        def run(self, info):
            callback(info)
            return [], info

    return _CallbackPP()


class _Reporter:
    """Receives everything yt-dlp reports and turns it into engine events."""

    def __init__(self, ctx: EngineContext, cancelled_exception: type):
        self._ctx = ctx
        self._cancelled = cancelled_exception
        self.had_error = False
        self.active = False  # only raise for cancelling while ydl.download() runs

    def _stop_if_cancelled(self) -> None:
        if self.active and self._ctx.cancel_event.is_set():
            raise self._cancelled("Cancelled by user")

    # --- logger interface (yt-dlp calls debug() for normal output too) -------------------

    def debug(self, message: str) -> None:
        self._ctx.emit(LogMessage("info", clean_message(message)))
        self._stop_if_cancelled()

    info = debug

    def warning(self, message: str) -> None:
        self._ctx.emit(LogMessage("warning", clean_message(message)))

    def error(self, message: str) -> None:
        self.had_error = True
        self._ctx.emit(LogMessage("error", clean_message(message)))

    # --- hooks ---------------------------------------------------------------------------

    def on_download_progress(self, status: dict) -> None:
        self._stop_if_cancelled()
        state = status.get("status")
        if state not in ("downloading", "finished"):
            return
        info = status.get("info_dict") or {}
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        self._ctx.emit(PartProgress(
            part_id=str(info.get("format_id") or ""),
            downloaded=int(status.get("downloaded_bytes") or 0),
            total=int(total) if total else None,
            speed=status.get("speed"),
            eta=status.get("eta"),
            finished=state == "finished",
            temp_file=status.get("tmpfilename") or status.get("filename") or "",
        ))

    def on_postprocessor(self, status: dict) -> None:
        if status.get("status") == "started":
            label = postprocessor_label(status.get("postprocessor") or "")
            if label:
                self._ctx.emit(PostProcessing(label))

    def on_item_started(self, info: dict) -> None:
        self._stop_if_cancelled()
        streams = info.get("requested_formats") or [info]
        video_id = str(info.get("id") or "")
        self._ctx.emit(ItemStarted(
            video_id=video_id,
            title=info.get("title") or video_id,
            url=info.get("webpage_url") or info.get("original_url") or "",
            thumbnail_url=youtube_thumbnail(info.get("thumbnail") or "", video_id, info.get("extractor_key") or ""),
            playlist_position=info.get("playlist_autonumber") or info.get("playlist_index"),
            playlist_count=info.get("n_entries") or info.get("playlist_count"),
            part_ids=[str(f.get("format_id") or "") for f in streams],
            part_sizes=[f.get("filesize") or f.get("filesize_approx") for f in streams],
            expected_file=info.get("_filename") or info.get("filename") or "",
        ))

    def on_item_finished(self, info: dict) -> None:
        self._ctx.emit(ItemFinished(
            file_path=info.get("filepath") or info.get("_filename") or "",
            video_id=str(info.get("id") or ""),
            title=info.get("title") or "",
        ))
