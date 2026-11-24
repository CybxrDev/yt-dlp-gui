"""
The two interchangeable ways of running yt-dlp (chosen in Settings → Engine & tools):

    library_engine.py  imports yt-dlp as a Python package inside this app (default).
                       Fast start, and can be updated from "Tools & updates".
    program_engine.py  runs the standalone yt-dlp executable as a separate process and
                       reads its output. Useful when you want yt-dlp to be completely
                       independent of this app (e.g. a system-wide yt-dlp you update yourself).

Both receive exactly the same arguments (see downloads/ytdlp_arguments.py) and report
progress with the same events (see downloads/models.py).
"""

from ytdlp_gui.downloads.engines.base import DownloadEngine, EngineContext, EngineError

ENGINE_LABELS = {
    "library": "yt-dlp Python library (built-in)",
    "cli": "yt-dlp program (separate executable)",
}


def create_engine(name: str) -> DownloadEngine:
    if name == "cli":
        from ytdlp_gui.downloads.engines.program_engine import ProgramEngine

        return ProgramEngine()
    from ytdlp_gui.downloads.engines.library_engine import LibraryEngine

    return LibraryEngine()


__all__ = ["DownloadEngine", "EngineContext", "EngineError", "ENGINE_LABELS", "create_engine"]
