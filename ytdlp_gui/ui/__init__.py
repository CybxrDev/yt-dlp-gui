"""
The Tkinter user interface (Tkinter ships with Python, so no UI libraries are needed).

    theme.py            light/dark colour palettes applied to every widget
    widgets.py          small reusable widgets (scrollable frame, placeholder text, tooltip)
    formatting.py       turning numbers into text: sizes, speeds, durations
    thumbnails.py       fetching thumbnails and converting them for display
    main_window.py      window layout: header, download form, tabs, status bar
    download_form.py    the links box and the per-download options
    jobs_panel.py       the "Downloads" tab: one card per job with progress bars
    history_panel.py    the "History" tab
    settings_dialog.py  the Settings window
    tools_dialog.py     the "Tools & updates" window
    log_window.py       a window showing one job's detailed yt-dlp log

UI code only runs on the main thread. Background work goes through App.run_in_background.
"""
