"""
Builds the standalone app with PyInstaller for the operating system it runs on.
(PyInstaller can't cross-compile: build the Windows app on Windows, etc. The GitHub
workflow in .github/workflows/build.yml builds all of them.)

    python -m pip install -r requirements-build.txt
    python packaging/build.py

Output in dist/:
    Windows  "yt-dlp GUI.exe"                 one file, nothing to install
    Linux    "yt-dlp-gui"                     one file
    macOS    "yt-dlp GUI.app" and a .zip      application bundle

FFmpeg and Deno are deliberately not bundled: the app downloads them on first start and
keeps them updated, so the app stays small and they can be updated on their own.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from ytdlp_gui import APP_ID, APP_NAME, APP_VERSION
    from ytdlp_gui.ui.app_icon import png_bytes

    if importlib.util.find_spec("yt_dlp") is None:
        sys.exit("yt-dlp is not installed. Run: python -m pip install -r requirements-build.txt")
    import PyInstaller.__main__

    icon = ROOT / "packaging" / "icon.png"
    icon.write_bytes(png_bytes(256))

    name = APP_ID if sys.platform.startswith("linux") else APP_NAME
    args = [
        str(ROOT / "run.py"),
        "--name", name,
        "--noconfirm",
        "--clean",
        "--windowed",  # no console window
        "--icon", str(icon),
        "--paths", str(ROOT),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    # yt-dlp ships its own PyInstaller hook; its YouTube challenge-solver scripts are data
    # files in the yt_dlp_ejs package, so collect that package completely.
    if importlib.util.find_spec("yt_dlp_ejs") is not None:
        args += ["--collect-all", "yt_dlp_ejs"]
    else:
        print("WARNING: yt-dlp-ejs is not installed; YouTube downloads will rely on remote scripts.")

    if sys.platform == "darwin":
        args += ["--onedir", "--osx-bundle-identifier", f"io.github.{APP_ID}"]
    else:
        args += ["--onefile"]

    print(f"Building {APP_NAME} {APP_VERSION} for {sys.platform}…")
    PyInstaller.__main__.run(args)

    if sys.platform == "darwin":
        app = ROOT / "dist" / f"{APP_NAME}.app"
        archive = ROOT / "dist" / f"{APP_ID}-{APP_VERSION}-macos.zip"
        archive.unlink(missing_ok=True)
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(archive)], check=True)
        shutil.rmtree(ROOT / "dist" / APP_NAME, ignore_errors=True)  # the loose onedir copy
        print(f"Done: {app}\n      {archive}")
    else:
        print(f"Done: {ROOT / 'dist'}")


if __name__ == "__main__":
    main()
