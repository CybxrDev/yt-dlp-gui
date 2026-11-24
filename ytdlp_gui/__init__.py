"""
yt-dlp GUI - a small, cross-platform desktop front-end for yt-dlp.

Package layout (every sub-package starts with a docstring describing its job):

    config/      user settings, download history, and where files live on disk
    downloads/   turning a download request into yt-dlp work (no UI code at all)
    tools/       finding, installing and updating external tools (yt-dlp, FFmpeg, Deno)
    ui/          the Tkinter user interface
    app.py       wires everything together and runs the window

Edit the constants below to rename or re-version the app.
"""

APP_NAME = "yt-dlp GUI"
APP_ID = "yt-dlp-gui"  # used for the data folder name and the HTTP user agent
APP_VERSION = "1.0.0"

# Optional "owner/repository" on GitHub where releases of THIS app are published.
# When set, the "Tools & updates" window also checks for new versions of the app itself.
APP_UPDATE_REPO = ""
