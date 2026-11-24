"""
Download logic - everything between "the user clicked Download" and "files on disk".
Contains no UI code, so it can be tested or reused on its own.

    models.py            data classes: requests, engine events, job snapshots
    url_parsing.py       find links in pasted text and in .txt files
    filename_pattern.py  "[title] - [id]" style patterns -> yt-dlp output templates
    format_selection.py  Format/Quality choices -> yt-dlp stream selection arguments
    ytdlp_arguments.py   the complete yt-dlp argument list for a request (both engines use it)
    progress_tracker.py  job %, current-media %, speeds and time estimates
    download_queue.py    runs jobs on background threads and reports to the UI
    engines/             the two ways of running yt-dlp: Python library or separate program
"""
