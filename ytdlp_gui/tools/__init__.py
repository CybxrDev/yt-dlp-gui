"""
External tools the app relies on, and how they are found, installed and updated.

    platform_info.py         operating system / CPU detection and subprocess helpers
    http_client.py           small HTTP helpers (JSON, redirects, file downloads with progress)
    tool_sources.py          WHERE each tool is downloaded from, per OS and CPU
    tool_manager.py          WHICH copy of each tool is used, its version, install/update
    ytdlp_library_loader.py  makes Python import an updated yt-dlp instead of the bundled one

The tools:
    yt-dlp (library)  the Python package doing the downloading (default engine)
    yt-dlp (program)  the standalone yt-dlp executable (alternative engine)
    FFmpeg            merges video + audio, converts audio, embeds thumbnails
    Deno              JavaScript runtime yt-dlp needs to solve YouTube's player challenges
"""
