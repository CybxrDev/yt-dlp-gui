"""
Turns the "Format" and "Quality" choices into yt-dlp arguments.

This is the one place that decides which streams are downloaded and how they become the
final file. The rules:

* Video formats: download the best video stream up to the chosen resolution plus the best
  audio stream, then merge them into the chosen container with FFmpeg (a copy, not a
  re-encode, so quality is untouched and it is fast).
    - MP4  prefers H.264 video + AAC audio, which plays everywhere. Above 1080p YouTube
           only offers VP9/AV1, and those are stored in the MP4 container instead.
    - MKV  takes the best streams whatever the codec (usually AV1/VP9 + Opus).
    - WebM prefers VP9 + Opus (the only codecs WebM allows).
  "--remux-video" is a safety net: if a site only offers a single file in another
  container, it is repackaged into the chosen one.
* Audio formats: download the best audio stream and convert it with FFmpeg when the
  source isn't already in that format.
* Thumbnails are embedded where the container supports it, converted to JPEG first so
  every player shows them.

"Resolution" uses the smaller side of the picture, so a vertical 1080x1920 Short counts
as 1080p, exactly like a horizontal 1920x1080 video.
"""

from __future__ import annotations

VIDEO_FORMATS = {
    "mp4": "MP4 video",
    "mkv": "MKV video",
    "webm": "WebM video",
}

AUDIO_FORMATS = {
    "mp3": "MP3 audio",
    "m4a": "M4A audio (AAC)",
    "opus": "Opus audio",
    "flac": "FLAC audio",
    "wav": "WAV audio",
}

FORMAT_CHOICES = {**VIDEO_FORMATS, **AUDIO_FORMATS}

RESOLUTION_CHOICES = {
    "best": "Best available",
    "2160": "2160p (4K)",
    "1440": "1440p (2K)",
    "1080": "1080p (Full HD)",
    "720": "720p (HD)",
    "480": "480p",
    "360": "360p",
    "240": "240p",
    "144": "144p",
}

# Containers that can carry an embedded cover image (yt-dlp limitation).
THUMBNAIL_EMBED_SUPPORTED = {"mp4", "mkv", "mp3", "m4a", "opus", "flac"}

# Audio stream to prefer for each audio format, so no conversion is needed when possible.
_AUDIO_SELECTORS = {
    "m4a": "ba[ext=m4a]/ba/b",
    "opus": "ba[acodec^=opus]/ba/b",
}

# Extra sort keys per video container (see "Sorting Formats" in the yt-dlp README).
# "vcodec:h264" = best codec no better than H.264, i.e. prefer H.264 over VP9/AV1.
_VIDEO_SORT = {
    "mp4": ["vcodec:h264", "acodec:aac"],
    "webm": ["vcodec:vp9", "acodec:opus"],
    "mkv": [],
}

_VIDEO_SELECTORS = {
    "webm": "bv*[ext=webm]+ba[ext=webm]/bv*+ba/b",
}


def is_audio_format(file_format: str) -> bool:
    return file_format in AUDIO_FORMATS


def format_arguments(
    file_format: str,
    resolution: str,
    *,
    embed_thumbnail: bool,
    embed_metadata: bool,
    embed_chapters: bool,
) -> list[str]:
    """yt-dlp arguments that select streams and produce the requested file type."""
    if file_format not in FORMAT_CHOICES:
        raise ValueError(f"Unknown file format: {file_format}")

    args: list[str] = []
    if is_audio_format(file_format):
        args += [
            "-f", _AUDIO_SELECTORS.get(file_format, "ba/b"),
            "--extract-audio",
            "--audio-format", file_format,
            "--audio-quality", "0",  # best quality when a conversion is needed
        ]
    else:
        sort = ["res" if resolution == "best" else f"res:{resolution}"]
        sort += _VIDEO_SORT.get(file_format, [])
        args += [
            "-f", _VIDEO_SELECTORS.get(file_format, "bv*+ba/b"),
            "-S", ",".join(sort),
            "--merge-output-format", file_format,
            "--remux-video", file_format,
        ]
        if embed_chapters:
            args.append("--embed-chapters")

    if embed_thumbnail and file_format in THUMBNAIL_EMBED_SUPPORTED:
        args += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
    if embed_metadata:
        args.append("--embed-metadata")
    return args


def describe(file_format: str, resolution: str) -> str:
    """Short human label such as "MP4 · 1080p" or "MP3"."""
    if is_audio_format(file_format):
        return file_format.upper()
    quality = "best" if resolution == "best" else f"{resolution}p"
    return f"{file_format.upper()} · {quality}"
