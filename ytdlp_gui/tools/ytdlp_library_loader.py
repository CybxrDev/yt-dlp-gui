"""
Lets the app use a newer yt-dlp than the one it was built with.

The compiled app contains a copy of the yt-dlp Python package. YouTube changes often, so
"Tools & updates" can download the newest yt-dlp (and the yt-dlp-ejs scripts it pins) from
PyPI into <data>/tools/yt-dlp-library. At start-up `activate()` installs an import hook so
`import yt_dlp` loads that copy instead of the bundled one.

Safety net: if the downloaded copy fails to import, the hook is removed and the bundled
copy is imported instead (the reason is shown in the Tools window).

Everything else in the app must import yt-dlp through `import_ytdlp()`.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import logging
import re
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_PACKAGES = ("yt_dlp", "yt_dlp_ejs")
_lock = threading.Lock()
_finder: "_OverrideFinder | None" = None
_library_dir: Path | None = None
_fallback_reason = ""


class _OverrideFinder(importlib.abc.MetaPathFinder):
    """Resolves yt_dlp / yt_dlp_ejs (and their sub-modules) from the override folder first."""

    def __init__(self, root: Path):
        self._root = str(root)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] not in _PACKAGES:
            return None
        search = [self._root] if "." not in fullname else path
        return importlib.machinery.PathFinder.find_spec(fullname, search)


def activate(library_dir: Path) -> None:
    """Call once at start-up, before anything imports yt_dlp."""
    global _finder, _library_dir
    _library_dir = library_dir
    if _finder is None and (library_dir / "yt_dlp" / "__init__.py").is_file():
        _finder = _OverrideFinder(library_dir)
        sys.meta_path.insert(0, _finder)
        log.info("Using updated yt-dlp from %s", library_dir)


def import_ytdlp():
    """Import and return the yt_dlp module (updated copy if present, else bundled)."""
    global _finder, _fallback_reason
    with _lock:
        try:
            first_import = "yt_dlp" not in sys.modules
            import yt_dlp

            if first_import:
                from yt_dlp.version import __version__

                log.info("Loaded yt-dlp %s from %s", __version__, getattr(yt_dlp, "__file__", "?"))
            return yt_dlp
        except Exception as exc:
            if _finder is None:
                raise
            log.exception("Updated yt-dlp failed to import; falling back to the bundled copy")
            _fallback_reason = f"The updated yt-dlp could not be loaded ({exc}); using the built-in copy."
            sys.meta_path.remove(_finder)
            _finder = None
            for name in list(sys.modules):
                if name.partition(".")[0] in _PACKAGES:
                    del sys.modules[name]
            import yt_dlp

            return yt_dlp


def is_available() -> bool:
    """True if some copy of yt_dlp can be imported (does not import it)."""
    try:
        return "yt_dlp" in sys.modules or importlib.util.find_spec("yt_dlp") is not None
    except (ImportError, ValueError):
        return False


def current_version() -> str | None:
    """Version of the yt-dlp copy this process uses (imports it if needed)."""
    try:
        import_ytdlp()
        from yt_dlp.version import __version__

        return __version__
    except Exception:
        return None


def loaded_version() -> str | None:
    """Version of yt-dlp if it has already been imported (never imports it)."""
    module = sys.modules.get("yt_dlp.version")
    return getattr(module, "__version__", None)


def using_updated_copy() -> bool:
    module = sys.modules.get("yt_dlp")
    if module is None or _library_dir is None or not getattr(module, "__file__", None):
        return False
    try:
        return Path(module.__file__).resolve().is_relative_to(_library_dir.resolve())
    except (OSError, ValueError):
        return False


def downloaded_version() -> str | None:
    """Version of the updated copy on disk (may be newer than the loaded one until restart)."""
    if _library_dir is None:
        return None
    try:
        text = (_library_dir / "yt_dlp" / "version.py").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"""^__version__\s*=\s*['"]([^'"]+)['"]""", text, re.MULTILINE)
    return match.group(1) if match else None


def fallback_reason() -> str:
    return _fallback_reason
