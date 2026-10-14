"""Detect which key legends to draw ('fr' for AZERTY, else 'us')."""

import ctypes
import os
import re
import subprocess
import sys


def legends_for(xkb_layout: str) -> str:
    # French and Belgian AZERTY share letter positions; close enough for legends
    return "fr" if xkb_layout.strip().lower()[:2] in ("fr", "be") else "us"


def parse_setxkbmap(out: str) -> str | None:
    """`setxkbmap -query`: 'layout:     fr,us' -> 'fr'."""
    m = re.search(r"^layout:\s*([^,\s]+)", out, re.MULTILINE)
    return m.group(1) if m else None


def parse_gsettings(out: str) -> str | None:
    """GNOME input sources: "[('xkb', 'fr+azerty'), ('xkb', 'us')]" -> 'fr'."""
    m = re.search(r"\('xkb',\s*'([^'+]+)", out)
    return m.group(1) if m else None


def parse_localectl(out: str) -> str | None:
    """`localectl status`: '    X11 Layout: fr' -> 'fr'."""
    m = re.search(r"X11 Layout:\s*([^,\s]+)", out)
    return m.group(1) if m else None


_GSETTINGS = (["gsettings", "get", "org.gnome.desktop.input-sources", "sources"], parse_gsettings)
_SETXKBMAP = (["setxkbmap", "-query"], parse_setxkbmap)
_LOCALECTL = (["localectl", "status"], parse_localectl)


def _linux_layout() -> str | None:
    if env := os.environ.get("XKB_DEFAULT_LAYOUT"):  # sway and other wlroots compositors
        return env.split(",")[0]
    # Under Wayland setxkbmap only sees XWayland's keymap, so ask the desktop first
    probes = ([_GSETTINGS, _LOCALECTL, _SETXKBMAP] if os.environ.get("WAYLAND_DISPLAY")
              else [_SETXKBMAP, _GSETTINGS, _LOCALECTL])
    for cmd, parse in probes:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if layout := parse(out):
            return layout
    return None


def detect_layout() -> str:
    if sys.platform == "win32":
        try:
            hkl = ctypes.windll.user32.GetKeyboardLayout(0)
            if hkl & 0x3FF == 0x0C:  # LANG_FRENCH
                return "fr"
        except (AttributeError, OSError):
            pass
    elif sys.platform.startswith("linux"):
        if layout := _linux_layout():
            return legends_for(layout)
    return "us"
