"""Small reusable widgets and helpers that plain Tkinter doesn't provide."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ytdlp_gui.ui.theme import Palette, ThemeManager


class ScrollableFrame(ttk.Frame):
    """A frame whose content (`self.inner`) scrolls vertically with the mouse wheel."""

    def __init__(self, master: tk.Misc, theme: ThemeManager):
        super().__init__(master)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, yscrollincrement=20)
        self._touchpad_pixels = 0
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", lambda _e: self._update_scroll_region())
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(event, self._on_wheel, add="+")
        try:  # Tk 9 reports trackpad gestures separately from mouse wheels
            self.bind_all("<TouchpadScroll>", self._on_touchpad, add="+")
        except tk.TclError:
            pass  # Tk 8.6
        theme.on_change(lambda p: self.canvas.configure(background=p.bg))

    def _update_scroll_region(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _pointer_is_inside(self, event: tk.Event) -> bool:
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):  # e.g. pointer over a closed popup
            return False
        return widget is not None and str(widget).startswith(str(self))

    def _can_scroll(self, event: tk.Event) -> bool:
        return self._pointer_is_inside(event) and self.inner.winfo_height() > self.canvas.winfo_height()

    def _on_wheel(self, event: tk.Event) -> None:
        if not self._can_scroll(event):
            return
        if event.num in (4, 5):  # Linux (X11) wheel buttons
            step = -3 if event.num == 4 else 3
        elif abs(event.delta) >= 120:  # Windows, and Tk 9 everywhere: 120 per wheel notch
            step = -3 * int(event.delta / 120)
        else:  # macOS with Tk 8.6: small deltas
            step = -event.delta
        if step:
            self.canvas.yview_scroll(step, "units")

    def _on_touchpad(self, event: tk.Event) -> None:
        if not self._can_scroll(event):
            return
        dy = ((event.delta & 0xFFFF) ^ 0x8000) - 0x8000  # low 16 bits = signed vertical delta
        self._touchpad_pixels += dy
        units = int(self._touchpad_pixels / 10)
        if units:
            self._touchpad_pixels -= units * 10
            self.canvas.yview_scroll(-units, "units")


class PlaceholderText(tk.Text):
    """A Text box that shows grey hint text while it is empty."""

    def __init__(self, master: tk.Misc, theme: ThemeManager, placeholder: str, **kwargs):
        super().__init__(master, wrap="word", undo=True, borderwidth=0, highlightthickness=1,
                         padx=8, pady=6, **kwargs)
        self._placeholder = placeholder
        self._showing = False
        self._palette: Palette = theme.palette
        theme.style_text_widget(self)
        theme.on_change(self._on_theme)
        self.bind("<FocusIn>", lambda _e: self._hide())
        self.bind("<FocusOut>", lambda _e: self._show_if_empty())
        self._show_if_empty()

    def get_text(self) -> str:
        return "" if self._showing else self.get("1.0", "end-1c")

    def set_text(self, text: str) -> None:
        self._hide()
        self.delete("1.0", "end")
        self.insert("1.0", text)
        if self.focus_get() is not self:
            self._show_if_empty()

    def _show_if_empty(self) -> None:
        if not self.get("1.0", "end-1c").strip():
            self.delete("1.0", "end")
            self.insert("1.0", self._placeholder)
            self.configure(foreground=self._palette.muted)
            self._showing = True

    def _hide(self) -> None:
        if self._showing:
            self.delete("1.0", "end")
            self.configure(foreground=self._palette.text)
            self._showing = False

    def _on_theme(self, palette: Palette) -> None:
        self._palette = palette
        self.configure(foreground=palette.muted if self._showing else palette.text)


class Tooltip:
    """Shows `text` in a small popup while the pointer rests on `widget`."""

    def __init__(self, widget: tk.Widget, text: str, theme: ThemeManager):
        self.widget = widget
        self.text = text
        self._theme = theme
        self._tip: tk.Toplevel | None = None
        self._after: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._after = self.widget.after(500, self._show)

    def _show(self) -> None:
        if self._tip or not self.text:
            return
        p = self._theme.palette
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self.text, justify="left", wraplength=360, background=p.surface_alt,
                 foreground=p.text, borderwidth=1, relief="solid", padx=8, pady=4).pack()

    def _hide(self, _event=None) -> None:
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


def open_path(path: str | Path) -> None:
    """Open a file or folder with the system's default application."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opening a user's own file
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_in_folder(path: str | Path) -> None:
    """Show a file selected in the file manager (or just open its folder on Linux)."""
    path = Path(path)
    if not path.exists():
        open_path(path.parent if path.parent.exists() else Path.home())
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        open_path(path.parent if path.is_file() else path)
