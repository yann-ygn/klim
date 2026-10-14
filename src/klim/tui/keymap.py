"""Physical TKL layout and a clickable keyboard map widget."""

import ctypes
import math
import sys
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from ..device import COLS

UNIT = 5  # terminal columns per key unit
KEY_HEIGHT = 2


def m(row: int, col: int) -> int:
    """Keymap index from matrix row (0 = bottom) and column."""
    return row * COLS + col


# Each row: (keymap index or None for a gap, width in key units). Indices come
# from the decoded matrix; the ISO '<' key lives in the F-row of the matrix.
ENTER = m(2, 13)
LAYOUT: list[list[tuple[int | None, float]]] = [
    [(m(5, 0), 1), (None, 1), *[(m(5, c), 1) for c in range(2, 6)], (None, .5),
     *[(m(5, c), 1) for c in range(6, 10)], (None, .5), *[(m(5, c), 1) for c in range(10, 14)],
     (None, .25), *[(m(5, c), 1) for c in range(14, 17)]],
    [*[(m(4, c), 1) for c in range(0, 13)], (m(4, 13), 2), (None, .25),
     *[(m(4, c), 1) for c in range(14, 17)]],
    [(m(3, 0), 1.5), *[(m(3, c), 1) for c in range(1, 13)], (ENTER, 1.5), (None, .25),
     *[(m(3, c), 1) for c in range(14, 17)]],
    [(m(2, 0), 1.75), *[(m(2, c), 1) for c in range(1, 13)], (ENTER, 1.25)],
    [(m(1, 0), 1.25), (m(5, 1), 1), *[(m(1, c), 1) for c in range(1, 11)], (m(1, 12), 2.75),
     (None, 1.25), (m(1, 15), 1)],
    [(m(0, 0), 1.25), (m(0, 1), 1.25), (m(0, 2), 1.25), (m(0, 5), 6.25), (m(0, 9), 1.25),
     (m(0, 10), 1.25), (m(0, 11), 1.25), (m(0, 13), 1.25), (None, .25),
     *[(m(0, c), 1) for c in range(14, 17)]],
]
ALL_KEYS = sorted({k for row in LAYOUT for k, _ in row if k is not None})

LEGENDS_US = {
    **{0x04 + i: chr(ord("A") + i) for i in range(26)},
    **{0x1E + i: str((i + 1) % 10) for i in range(10)},
    0x28: "Enter", 0x29: "Esc", 0x2A: "Bksp", 0x2B: "Tab", 0x2C: "", 0x2D: "-", 0x2E: "=",
    0x2F: "[", 0x30: "]", 0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",", 0x37: ".",
    0x38: "/", 0x39: "Caps", **{0x3A + i: f"F{i + 1}" for i in range(12)}, 0x46: "PrSc",
    0x47: "ScLk", 0x48: "Paus", 0x49: "Ins", 0x4A: "Home", 0x4B: "PgUp", 0x4C: "Del",
    0x4D: "End", 0x4E: "PgDn", 0x4F: "→", 0x50: "←", 0x51: "↓", 0x52: "↑", 0x64: "\\",
    0x65: "Menu", 0xE0: "Ctrl", 0xE1: "Shift", 0xE2: "Alt", 0xE3: "Win", 0xE4: "Ctrl",
    0xE5: "Shift", 0xE6: "Alt", 0xE7: "Win",
}
LEGENDS_FR = {
    **LEGENDS_US,
    0x14: "A", 0x1A: "Z", 0x04: "Q", 0x1D: "W", 0x33: "M", 0x10: ",", 0x36: ";", 0x37: ":",
    0x38: "!", 0x35: "²", 0x2D: ")", 0x2F: "^", 0x30: "$", 0x34: "ù", 0x31: "*", 0x64: "<",
    0x28: "Entrée", 0xE6: "AltGr", 0x39: "Verr",
}
LEGENDS = {"us": LEGENDS_US, "fr": LEGENDS_FR}


def detect_layout() -> str:
    """'fr' if Windows is using a French keyboard layout, else 'us'."""
    if sys.platform == "win32":
        try:
            hkl = ctypes.windll.user32.GetKeyboardLayout(0)
            if hkl & 0x3FF == 0x0C:  # LANG_FRENCH
                return "fr"
        except (AttributeError, OSError):
            pass
    return "us"


@dataclass
class KeyRect:
    k: int
    x0: int
    x1: int
    y: int
    continuation: bool = False  # second part of a key spanning two rows (ISO Enter)


def luminance(rgb: bytes) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class KeyboardMap(Widget, can_focus=True):
    """Draws the keyboard with per-key colors; click/drag or arrows+space to select."""

    DEFAULT_CSS = """
    KeyboardMap {
        width: auto;
        height: auto;
        padding: 0 1;
        border: tall $panel;
    }
    KeyboardMap:focus {
        border: tall $accent;
    }
    """
    BINDINGS = [
        Binding("left", "move(-1, 0)", show=False),
        Binding("right", "move(1, 0)", show=False),
        Binding("up", "move(0, -1)", show=False),
        Binding("down", "move(0, 1)", show=False),
        Binding("space", "toggle", "Select key"),
        Binding("ctrl+a", "select_all", "Select all"),
        Binding("escape", "select_none", "Clear selection"),
    ]

    selection: reactive[frozenset[int]] = reactive(frozenset(), always_update=True)
    cursor: reactive[int | None] = reactive(None)

    class SelectionChanged(Message):
        def __init__(self, keymap: "KeyboardMap", selection: frozenset[int]):
            super().__init__()
            self.keymap = keymap
            self.selection = selection

        @property
        def control(self) -> "KeyboardMap":
            return self.keymap

    def __init__(self, layout: str = "us", *, id: str | None = None):
        super().__init__(id=id)
        self.legends = LEGENDS.get(layout, LEGENDS_US)
        self.keymap: bytes | None = None
        self.key_colors: dict[int, bytes] = {}
        self.dimmed: set[int] = set()  # drawn crossed out (e.g. disabled keys)
        self.rects = self._layout()
        self._drag_add: bool | None = None

    @staticmethod
    def _layout() -> list[KeyRect]:
        rects, seen = [], set()
        for r, row in enumerate(LAYOUT):
            y = r * KEY_HEIGHT + (1 if r else 0)  # blank line under the F-row
            u = 0.0
            for k, w in row:
                if k is not None:
                    x0, x1 = math.floor(u * UNIT), math.floor((u + w) * UNIT) - 1
                    rects.append(KeyRect(k, x0, x1, y, continuation=k in seen))
                    seen.add(k)
                u += w
        return rects

    def get_content_width(self, container, viewport) -> int:
        return max(r.x1 for r in self.rects)

    def get_content_height(self, container, viewport, width) -> int:
        return max(r.y for r in self.rects) + KEY_HEIGHT

    def label(self, k: int) -> str:
        if self.keymap is None:
            return ""
        typ, usage = self.keymap[4 * k], self.keymap[4 * k + 2]
        if typ == 2:
            return "Fn"
        return self.legends.get(usage, f"{usage:02x}" if usage else "")

    def set_colors(self, colors: dict[int, bytes]):
        self.key_colors = colors
        self.refresh()

    def render(self) -> Text:
        height = self.get_content_height(None, None, 0)
        lines = [Text() for _ in range(height)]
        widths = [0] * height
        base = self.rich_style
        for rect in sorted(self.rects, key=lambda r: (r.y, r.x0)):
            rgb = self.key_colors.get(rect.k, b"\x30\x30\x30")
            fg = "#000000" if luminance(rgb) > 140 else "#ffffff"
            bg = "#{:02x}{:02x}{:02x}".format(*rgb)
            width = rect.x1 - rect.x0
            selected = rect.k in self.selection
            is_cursor = rect.k == self.cursor and self.has_focus
            label = ("" if rect.continuation else self.label(rect.k))[:width].center(width)
            label_style = Style(color=fg, bgcolor=bg, bold=selected or is_cursor,
                                underline=is_cursor, strike=rect.k in self.dimmed)
            under = ("━" if selected else " ") * width
            for dy, (text, style) in enumerate(((label, label_style),
                                                (under, Style(color=fg, bgcolor=bg)))):
                y = rect.y + dy
                if rect.x0 > widths[y]:
                    lines[y].append(" " * (rect.x0 - widths[y]), base)
                lines[y].append(text, style)
                widths[y] = rect.x1
        return Text("\n").join(lines)

    # --- interaction ------------------------------------------------------

    def key_at(self, x: int, y: int) -> int | None:
        for r in self.rects:
            if r.x0 <= x < r.x1 and r.y <= y < r.y + KEY_HEIGHT:
                return r.k
        return None

    def _set_selection(self, selection: frozenset[int]):
        if selection != self.selection:
            self.selection = selection
            self.post_message(self.SelectionChanged(self, selection))

    def _paint(self, k: int | None):
        if k is None or self._drag_add is None:
            return
        self.cursor = k
        sel = set(self.selection)
        (sel.add if self._drag_add else sel.discard)(k)
        self._set_selection(frozenset(sel))

    def on_mouse_down(self, event: events.MouseDown):
        k = self.key_at(event.x, event.y)
        if k is None:
            return
        self.focus()
        self._drag_add = k not in self.selection
        self.capture_mouse()
        self._paint(k)

    def on_mouse_move(self, event: events.MouseMove):
        if self._drag_add is not None:
            self._paint(self.key_at(event.x, event.y))

    def on_mouse_up(self, event: events.MouseUp):
        self._drag_add = None
        self.release_mouse()

    def watch_cursor(self):
        self.refresh()

    def watch_selection(self):
        self.refresh()

    def on_focus(self):
        if self.cursor is None:
            self.cursor = self.rects[0].k
        self.refresh()

    def on_blur(self):
        self.refresh()

    def _cursor_rect(self) -> KeyRect:
        return next((r for r in self.rects if r.k == self.cursor), self.rects[0])

    def action_move(self, dx: int, dy: int):
        cur = self._cursor_rect()
        cx = (cur.x0 + cur.x1) / 2
        if dx:
            row = sorted((r for r in self.rects if r.y == cur.y), key=lambda r: r.x0)
            i = next(i for i, r in enumerate(row) if r is cur) + dx
            if 0 <= i < len(row):
                self.cursor = row[i].k
        else:
            ys = sorted({r.y for r in self.rects})
            i = ys.index(cur.y) + dy
            if 0 <= i < len(ys):
                row = [r for r in self.rects if r.y == ys[i]]
                self.cursor = min(row, key=lambda r: abs((r.x0 + r.x1) / 2 - cx)).k

    def action_toggle(self):
        if self.cursor is not None:
            self._set_selection(self.selection ^ {self.cursor})

    def action_select_all(self):
        self._set_selection(frozenset(ALL_KEYS))

    def action_select_none(self):
        self._set_selection(frozenset())
