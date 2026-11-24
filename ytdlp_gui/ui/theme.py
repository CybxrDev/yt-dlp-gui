"""
Light and dark themes.

All ttk widgets use the built-in "clam" theme, recoloured from one Palette, so both modes
look the same on Windows, macOS and Linux. Plain tk widgets (Text, Canvas, Menu, Listbox)
don't follow ttk styles; code that creates them registers a callback with `on_change`
to recolour them whenever the theme changes.

To tweak colours, edit LIGHT / DARK below. Style names used around the UI:
    Card.TFrame / Card.TLabel / CardMuted.TLabel   content on a raised "card"
    Muted.TLabel, Heading.TLabel, Small.TLabel     secondary / title / small text
    Accent.TButton                                 the main call-to-action button
    Link.TButton                                   a button that looks like a link
    Job.Horizontal.TProgressbar                    the whole-job progress bar
"""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str  # window background
    surface: str  # cards and input fields
    surface_alt: str  # buttons, headers
    border: str
    text: str
    muted: str  # secondary text
    accent: str
    accent_hover: str
    accent_text: str
    success: str
    warning: str
    danger: str
    selection: str
    trough: str  # empty part of progress bars


LIGHT = Palette(
    name="light", bg="#f3f4f6", surface="#ffffff", surface_alt="#e8eaee", border="#d3d7de",
    text="#1f2328", muted="#62686f", accent="#2563eb", accent_hover="#1d4ed8", accent_text="#ffffff",
    success="#16833a", warning="#9a6700", danger="#cf222e", selection="#cfe0ff", trough="#e2e5ea",
)

DARK = Palette(
    name="dark", bg="#16171a", surface="#212327", surface_alt="#2c2f35", border="#3a3e46",
    text="#e8eaed", muted="#9aa0a8", accent="#4f8cff", accent_hover="#6c9fff", accent_text="#ffffff",
    success="#46c46e", warning="#e3b341", danger="#ff6b6b", selection="#2d4a7c", trough="#2c2f35",
)


def system_prefers_dark() -> bool:
    """Best-effort detection of the operating system's dark mode."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=3)
            return "dark" in out.stdout.lower()
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=3)
        if "dark" in out.stdout.lower():
            return True
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                             capture_output=True, text=True, timeout=3)
        return "dark" in out.stdout.lower()
    except Exception:
        return False


class ThemeManager:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.palette = LIGHT
        self._listeners: list = []
        self._style = ttk.Style(root)
        self._style.theme_use("clam")
        base = tkfont.nametofont("TkDefaultFont")
        size = base.cget("size") or 10
        self.fonts = {
            "base": base,
            "bold": _derive(base, weight="bold"),
            "heading": _derive(base, size=_bigger(size, 3), weight="bold"),
            "title": _derive(base, size=_bigger(size, 1), weight="bold"),
            "small": _derive(base, size=_bigger(size, -1)),
            "mono": tkfont.nametofont("TkFixedFont"),
        }

    def apply(self, mode: str) -> None:
        """mode: 'light', 'dark' or 'system'."""
        dark = mode == "dark" or (mode == "system" and system_prefers_dark())
        self.palette = DARK if dark else LIGHT
        self._configure_styles(self.palette)
        for callback in list(self._listeners):
            try:
                callback(self.palette)
            except tk.TclError:
                self._listeners.remove(callback)  # its widget was destroyed

    def on_change(self, callback: Callable[[Palette], None]) -> None:
        """Call `callback(palette)` now and whenever the theme changes."""
        self._listeners.append(callback)
        callback(self.palette)

    def style_text_widget(self, widget: tk.Text | tk.Listbox | tk.Canvas, surface: bool = True) -> None:
        """Keep a plain tk widget's colours in sync with the theme."""

        def recolour(p: Palette) -> None:
            bg = p.surface if surface else p.bg
            options = {"background": bg, "highlightbackground": p.border, "highlightcolor": p.accent}
            if not isinstance(widget, tk.Canvas):
                options.update(foreground=p.text, selectbackground=p.selection, selectforeground=p.text)
            if isinstance(widget, tk.Text):
                options.update(insertbackground=p.text)
            widget.configure(**options)

        self.on_change(recolour)

    # ----------------------------------------------------------------------------------

    def _configure_styles(self, p: Palette) -> None:
        s = self._style
        f = self.fonts
        self.root.configure(background=p.bg)

        s.configure(".", background=p.bg, foreground=p.text, bordercolor=p.border, darkcolor=p.bg,
                    lightcolor=p.bg, troughcolor=p.trough, focuscolor=p.accent, selectbackground=p.selection,
                    selectforeground=p.text, insertcolor=p.text, fieldbackground=p.surface, font=f["base"])
        s.map(".", foreground=[("disabled", p.muted)])

        # Frames and labels
        s.configure("TFrame", background=p.bg)
        s.configure("Card.TFrame", background=p.surface, bordercolor=p.border, relief="solid", borderwidth=1)
        s.configure("CardPlain.TFrame", background=p.surface, borderwidth=0)
        s.configure("TLabel", background=p.bg, foreground=p.text)
        s.configure("Muted.TLabel", foreground=p.muted)
        s.configure("Small.TLabel", foreground=p.muted, font=f["small"])
        s.configure("Heading.TLabel", font=f["heading"])
        s.configure("Bold.TLabel", font=f["bold"])
        s.configure("Card.TLabel", background=p.surface)
        s.configure("CardTitle.TLabel", background=p.surface, font=f["title"])
        s.configure("CardMuted.TLabel", background=p.surface, foreground=p.muted, font=f["small"])
        s.configure("CardError.TLabel", background=p.surface, foreground=p.danger, font=f["small"])
        s.configure("Error.TLabel", foreground=p.danger)
        s.configure("Success.TLabel", foreground=p.success)
        s.configure("Warning.TLabel", foreground=p.warning)
        s.configure("TLabelframe", background=p.bg, bordercolor=p.border)
        s.configure("TLabelframe.Label", background=p.bg, foreground=p.muted, font=f["bold"])
        s.configure("TSeparator", background=p.border)

        # Buttons
        # width=-6: buttons are at least 6 characters wide (clam's default of 11 wastes space)
        s.configure("TButton", background=p.surface_alt, foreground=p.text, bordercolor=p.border,
                    lightcolor=p.surface_alt, darkcolor=p.surface_alt, padding=(10, 4), focusthickness=1,
                    focuscolor=p.accent, width=-6)
        s.map("TButton",
              background=[("disabled", p.bg), ("pressed", p.border), ("active", p.border)],
              lightcolor=[("pressed", p.border), ("active", p.border)],
              darkcolor=[("pressed", p.border), ("active", p.border)])
        s.configure("Accent.TButton", background=p.accent, foreground=p.accent_text, bordercolor=p.accent,
                    lightcolor=p.accent, darkcolor=p.accent, font=f["bold"], padding=(18, 6))
        s.map("Accent.TButton",
              background=[("disabled", p.surface_alt), ("pressed", p.accent_hover), ("active", p.accent_hover)],
              lightcolor=[("pressed", p.accent_hover), ("active", p.accent_hover)],
              darkcolor=[("pressed", p.accent_hover), ("active", p.accent_hover)],
              foreground=[("disabled", p.muted)])
        s.configure("Link.TButton", background=p.bg, foreground=p.accent, bordercolor=p.bg, lightcolor=p.bg,
                    darkcolor=p.bg, padding=(2, 0), relief="flat", borderwidth=0, width=0)
        s.map("Link.TButton", background=[("active", p.bg), ("pressed", p.bg)],
              foreground=[("active", p.accent_hover), ("disabled", p.muted)],
              lightcolor=[("active", p.bg)], darkcolor=[("active", p.bg)], bordercolor=[("active", p.bg)])
        s.configure("Card.TButton", padding=(8, 1), width=0)
        s.configure("TMenubutton", background=p.surface_alt, foreground=p.text, bordercolor=p.border,
                    lightcolor=p.surface_alt, darkcolor=p.surface_alt, arrowcolor=p.text, padding=(8, 4))
        s.map("TMenubutton", background=[("active", p.border)])

        # Inputs
        s.configure("TEntry", fieldbackground=p.surface, foreground=p.text, bordercolor=p.border,
                    lightcolor=p.surface, darkcolor=p.surface, insertcolor=p.text, padding=4)
        s.map("TEntry", bordercolor=[("focus", p.accent)], lightcolor=[("focus", p.accent)],
              fieldbackground=[("disabled", p.bg)])
        s.configure("TCombobox", fieldbackground=p.surface, background=p.surface_alt, foreground=p.text,
                    arrowcolor=p.text, bordercolor=p.border, lightcolor=p.surface, darkcolor=p.surface, padding=4)
        s.map("TCombobox",
              fieldbackground=[("readonly", p.surface), ("disabled", p.bg)],
              foreground=[("disabled", p.muted), ("readonly", p.text)],
              selectbackground=[("readonly", p.surface)], selectforeground=[("readonly", p.text)],
              background=[("active", p.border), ("pressed", p.border)],
              bordercolor=[("focus", p.accent)], arrowcolor=[("disabled", p.muted)])
        s.configure("TSpinbox", fieldbackground=p.surface, foreground=p.text, background=p.surface_alt,
                    arrowcolor=p.text, bordercolor=p.border, lightcolor=p.surface, darkcolor=p.surface, padding=4)
        for name in ("TCheckbutton", "TRadiobutton"):
            s.configure(name, background=p.bg, foreground=p.text, indicatorbackground=p.surface,
                        indicatorforeground=p.accent_text, upperbordercolor=p.border, lowerbordercolor=p.border,
                        focuscolor=p.bg)
            s.map(name, background=[("active", p.bg)],
                  indicatorbackground=[("selected", p.accent), ("pressed", p.surface_alt)],
                  upperbordercolor=[("selected", p.accent)], lowerbordercolor=[("selected", p.accent)])

        # Notebook (tabs)
        s.configure("TNotebook", background=p.bg, bordercolor=p.border, lightcolor=p.bg, darkcolor=p.bg,
                    tabmargins=(0, 0, 0, 0))
        s.configure("TNotebook.Tab", background=p.bg, foreground=p.muted, bordercolor=p.border,
                    lightcolor=p.bg, darkcolor=p.bg, padding=(16, 6), font=f["bold"])
        s.map("TNotebook.Tab", background=[("selected", p.surface)], foreground=[("selected", p.text)],
              lightcolor=[("selected", p.surface)], expand=[("selected", (0, 0, 0, 0))])

        # Lists
        s.configure("Treeview", background=p.surface, fieldbackground=p.surface, foreground=p.text,
                    bordercolor=p.border, lightcolor=p.surface, darkcolor=p.surface)
        s.map("Treeview", background=[("selected", p.selection)], foreground=[("selected", p.text)])
        s.configure("Treeview.Heading", background=p.surface_alt, foreground=p.text, bordercolor=p.border,
                    lightcolor=p.surface_alt, darkcolor=p.surface_alt, relief="flat", font=f["bold"])
        s.map("Treeview.Heading", background=[("active", p.border)])

        # Progress bars and scrollbars
        s.configure("Horizontal.TProgressbar", background=p.accent, troughcolor=p.trough, bordercolor=p.trough,
                    lightcolor=p.accent, darkcolor=p.accent, thickness=8)
        s.configure("Job.Horizontal.TProgressbar", background=p.success, troughcolor=p.trough,
                    bordercolor=p.trough, lightcolor=p.success, darkcolor=p.success, thickness=8)
        for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            s.configure(name, background=p.surface_alt, troughcolor=p.bg, bordercolor=p.bg, arrowcolor=p.muted,
                        lightcolor=p.surface_alt, darkcolor=p.surface_alt, gripcount=0)
            s.map(name, background=[("active", p.border)])

        # Drop-down lists of comboboxes and menus are plain tk widgets
        self.root.option_add("*TCombobox*Listbox.background", p.surface)
        self.root.option_add("*TCombobox*Listbox.foreground", p.text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", p.selection)
        self.root.option_add("*TCombobox*Listbox.selectForeground", p.text)
        self.root.option_add("*Menu.background", p.surface)
        self.root.option_add("*Menu.foreground", p.text)
        self.root.option_add("*Menu.activeBackground", p.selection)
        self.root.option_add("*Menu.activeForeground", p.text)
        self._recolour_existing_popups(self.root, p)

    def _recolour_existing_popups(self, widget: tk.Misc, p: Palette) -> None:
        """option_add only affects new widgets; fix combobox lists and menus already created."""
        for child in widget.winfo_children():
            if isinstance(child, ttk.Combobox):
                try:
                    popdown = child.tk.eval(f"ttk::combobox::PopdownWindow {child}")
                    child.tk.call(f"{popdown}.f.l", "configure", "-background", p.surface, "-foreground", p.text,
                                  "-selectbackground", p.selection, "-selectforeground", p.text)
                except tk.TclError:
                    pass
            elif isinstance(child, tk.Menu):
                child.configure(background=p.surface, foreground=p.text, activebackground=p.selection,
                                activeforeground=p.text)
            self._recolour_existing_popups(child, p)


def _derive(font: tkfont.Font, **changes) -> tkfont.Font:
    derived = tkfont.Font(font=font)
    derived.configure(**changes)
    return derived


def _bigger(size: int, step: int) -> int:
    """Font sizes may be negative (pixels) in Tk; grow/shrink them in the right direction."""
    return size - step if size < 0 else size + step
