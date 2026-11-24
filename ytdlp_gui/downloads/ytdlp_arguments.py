"""
The complete list of yt-dlp command-line arguments for a download request.

Both engines use this one function, so a download behaves the same whichever engine is
selected:
  * the program engine passes the arguments to the yt-dlp executable as they are;
  * the library engine converts them with yt-dlp's own `yt_dlp.parse_options()`.

Run with "--ignore-config" so a yt-dlp config file on the user's machine can't change
what the app does. No login or token is ever required; browser cookies are only used if
switched on in Settings.
"""

from __future__ import annotations

from ytdlp_gui.config.settings import Settings
from ytdlp_gui.downloads.filename_pattern import to_output_template
from ytdlp_gui.downloads.format_selection import format_arguments
from ytdlp_gui.downloads.models import DownloadRequest
from ytdlp_gui.tools.tool_manager import ResolvedTools


def build_arguments(request: DownloadRequest, settings: Settings, tools: ResolvedTools) -> list:
    """Arguments for one request, without the URL(s)."""
    args = [
        "--ignore-config",
        "--no-mtime",  # files get today's date instead of the upload date
        "--yes-playlist" if request.whole_playlist else "--no-playlist",
    ]
    args += format_arguments(
        request.file_format,
        request.resolution,
        embed_thumbnail=settings.embed_thumbnail,
        embed_metadata=settings.embed_metadata,
        embed_chapters=settings.embed_chapters,
    )
    args += ["--paths", request.output_dir, "--output", to_output_template(request.filename_pattern)]

    if tools.ffmpeg_dir is not None:
        args += ["--ffmpeg-location", str(tools.ffmpeg_dir)]
    if tools.js_runtime is not None:
        runtime_name, runtime_path = tools.js_runtime
        args += ["--no-js-runtimes", "--js-runtimes", f"{runtime_name}:{runtime_path}"]
    if settings.allow_remote_components:
        args += ["--remote-components", "ejs:github"]
    if settings.cookies_from_browser:
        args += ["--cookies-from-browser", settings.cookies_from_browser]
    return args
