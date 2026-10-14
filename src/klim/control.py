"""Keyboard settings logic shared by the CLI and the TUI.

Works on top of `device.Keyboard` (or anything with the same methods) and
raises exceptions instead of printing: KeyError for unknown keys, ValueError
for out-of-range values. The firmware stores whatever it is sent, so every
value is validated here before it reaches the keyboard.
"""

from dataclasses import dataclass
from pathlib import Path

from . import keys
from .device import (BRIGHTNESS_MAX, COLS, CUSTOM_MODE_BASE, DEFAULT_PALETTE, KEY_MASK_LEN,
                     MODE_NAMES, MULTICOLOR, MULTICOLOR_ONLY, RESPONSE_TIMES_MS, ROWS, SLOTS,
                     SPEED_SLOWEST, State, key_enabled, keymap_to_led, set_key_enabled,
                     usage_to_index)

# Names of the palette entries' factory colors (entries can be recolored)
COLORS = ["red", "green", "yellow", "blue", "cyan", "magenta", "white", "multi"]
DIRECTIONS = ["right", "left", "up", "down"]  # which way the animation moves; 1..4 on the wire
WIN_KEYS = ("lwin", "rwin")
ALL_KEYS_ENABLED = bytes([0xFF, 0xFF, 0x1F] * ROWS)
RGB_SLOT_SIZE = 512
LEDS = ROWS * COLS


def speed_from_raw(raw: int) -> int:
    """Raw animation delay -> user-facing speed, 1 (slowest) .. 10 (fastest)."""
    return SPEED_SLOWEST + 1 - raw


def speed_to_raw(speed: int) -> int:
    return SPEED_SLOWEST + 1 - speed


@dataclass
class Info:
    state: State
    palette: list[bytes]
    game_mode: bool
    disabled_keys: list[str]
    key_mask: bytes
    report_rate: int | None
    response_time: int
    firmware: str

    @property
    def win_lock(self) -> bool:
        return any(n in self.disabled_keys for n in WIN_KEYS)

    @property
    def disabled_indices(self) -> frozenset[int]:
        return frozenset(k for k in range(ROWS * COLS) if not key_enabled(self.key_mask, k))

    @property
    def speed(self) -> int:
        return speed_from_raw(self.state.speed)

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.state.mode, "?")

    @property
    def color_name(self) -> str:
        return COLORS[self.state.color - 1] if 1 <= self.state.color <= MULTICOLOR else "?"

    @property
    def color_rgb(self) -> bytes | None:
        """Actual RGB of the active palette entry, None for multicolor."""
        c = self.state.color
        return self.palette[c - 1] if 1 <= c < MULTICOLOR else None

    @property
    def direction_name(self) -> str:
        d = self.state.direction
        return DIRECTIONS[d - 1] if 1 <= d <= len(DIRECTIONS) else "?"


class Klim:
    def __init__(self, kb):
        self.kb = kb
        self._keymap: bytes | None = None

    @property
    def keymap(self) -> bytes:
        """Cached: this tool never writes the keymap."""
        if self._keymap is None:
            self._keymap = self.kb.read_keymap()
        return self._keymap

    def info(self) -> Info:
        mask = bytes(self.kb.read_key_mask())
        return Info(
            state=self.kb.get_state(),
            palette=self.kb.get_palette(),
            game_mode=self.kb.get_game_mode(),
            disabled_keys=self.disabled_keys(mask),
            key_mask=mask,
            report_rate=self.kb.get_report_rate(),
            response_time=self.kb.get_response_time(),
            firmware=self.kb.get_firmware_version(),
        )

    # --- lighting -------------------------------------------------------

    def set_lighting(self, mode: int | None = None, speed: int | None = None,
                     brightness: int | None = None, color: int | None = None,
                     direction: int | None = None) -> State:
        """Change any subset of the lighting state; speed is user-facing 1..10."""
        s = self.kb.get_state()
        if mode is not None:
            if mode not in MODE_NAMES:
                raise ValueError(f"unknown mode 0x{mode:02x}")
            s.mode = mode
        if speed is not None:
            if not 1 <= speed <= SPEED_SLOWEST:
                raise ValueError(f"speed must be 1..{SPEED_SLOWEST}")
            s.speed = speed_to_raw(speed)
        if brightness is not None:
            if not 0 <= brightness <= BRIGHTNESS_MAX:
                raise ValueError(f"brightness must be 0..{BRIGHTNESS_MAX}")
            s.brightness = brightness
        if color is not None:
            if not 1 <= color <= MULTICOLOR:
                raise ValueError(f"color must be 1..{MULTICOLOR}")
            s.color = color
        if direction is not None:
            if not 1 <= direction <= len(DIRECTIONS):
                raise ValueError(f"direction must be 1..{len(DIRECTIONS)}")
            s.direction = direction
        if s.mode in MULTICOLOR_ONLY:
            s.color = MULTICOLOR
        self.kb.set_state(s)
        return s

    def set_palette(self, entry: int, rgb: bytes):
        """Recolor palette entry 1..7; takes effect immediately."""
        if not 1 <= entry <= len(DEFAULT_PALETTE):
            raise ValueError(f"palette entry must be 1..{len(DEFAULT_PALETTE)}")
        if len(rgb) != 3:
            raise ValueError("color must be 3 bytes")
        self.kb.set_palette(entry - 1, rgb)

    def reset_palette(self):
        for i, rgb in enumerate(DEFAULT_PALETTE):
            self.kb.set_palette(i, rgb)

    # --- keys -----------------------------------------------------------

    def key_name(self, k: int) -> str:
        """Name of the key at keymap index k ('#k' for non-standard entries)."""
        typ, usage = self.keymap[4 * k], self.keymap[4 * k + 2]
        return keys.name_of(usage) if typ == 0 and usage else f"#{k}"

    def key_indices(self, names: list[str], strict: bool = True) -> list[int]:
        """Resolve key names/groups to keymap indices."""
        index = usage_to_index(self.keymap)
        out = []
        for name in names:
            for usage in keys.resolve(name):
                if usage in index:
                    out.append(index[usage])
                elif strict:
                    raise KeyError(f"key '{name}' (usage 0x{usage:02x}) not in keymap")
        return out

    def disabled_keys(self, mask: bytes | None = None) -> list[str]:
        if mask is None:
            mask = self.kb.read_key_mask()
        return [self.key_name(k) for k in range(ROWS * COLS)
                if not key_enabled(mask, k) and self.keymap[4 * k + 2]]

    def set_keys_enabled(self, names: list[str], enabled: bool, strict: bool = True):
        mask = self.kb.read_key_mask()
        for k in self.key_indices(names, strict):
            set_key_enabled(mask, k, enabled)
        self.kb.write_key_mask(mask)

    def set_disabled(self, indices: set[int]):
        """Disable exactly these keymap indices; every other key is enabled."""
        mask = bytearray(ALL_KEYS_ENABLED)
        for k in indices:
            set_key_enabled(mask, k, False)
        self.kb.write_key_mask(mask)

    def enable_all_keys(self):
        self.kb.write_key_mask(ALL_KEYS_ENABLED)

    def set_win_lock(self, on: bool):
        self.set_keys_enabled(list(WIN_KEYS), not on, strict=False)

    def set_game_mode(self, on: bool):
        self.kb.set_game_mode(on)

    # --- USB ------------------------------------------------------------

    def set_report_rate(self, hz: int):
        self.kb.set_report_rate(hz)

    def set_response_time(self, ms: int):
        self.kb.set_response_time(ms)

    # --- per-key RGB ----------------------------------------------------

    def default_slot(self) -> int:
        """Active DIY slot (0-based), or 0 if a built-in effect is showing."""
        mode = self.kb.get_state().mode
        return mode - CUSTOM_MODE_BASE if mode >= CUSTOM_MODE_BASE else 0

    def read_slot(self, slot: int) -> bytearray:
        """128 x [0, R, G, B], indexed by LED number."""
        return self.kb.read_rgb(slot)

    def write_slot(self, slot: int, buf: bytes):
        """Upload a slot and switch to its DIY mode (which also makes it visible)."""
        if not 0 <= slot < SLOTS:
            raise ValueError(f"slot must be 0..{SLOTS - 1}")
        self.kb.write_rgb(slot, bytes(buf))
        self.set_lighting(mode=CUSTOM_MODE_BASE + slot)

    @staticmethod
    def filled_slot(rgb: bytes) -> bytearray:
        buf = bytearray(RGB_SLOT_SIZE)
        for led in range(LEDS):
            buf[4 * led + 1:4 * led + 4] = rgb
        return buf

    def paint(self, buf: bytearray, k: int, rgb: bytes):
        """Set the color of keymap index k in a slot buffer."""
        led = keymap_to_led(k)
        buf[4 * led + 1:4 * led + 4] = rgb

    def key_color(self, buf: bytes, k: int) -> bytes:
        led = keymap_to_led(k)
        return bytes(buf[4 * led + 1:4 * led + 4])

    def paint_keys(self, slot: int, assignments: list[tuple[list[str], bytes]],
                   base: bytes | None = None):
        """Color named keys in a slot (starting from `base` or its current colors)."""
        buf = self.filled_slot(base) if base is not None else self.read_slot(slot)
        for names, rgb in assignments:
            for k in self.key_indices(names):
                self.paint(buf, k, rgb)
        self.write_slot(slot, buf)

    # --- backup / restore -----------------------------------------------

    def backup(self, d: Path) -> list[str]:
        kb = self.kb
        d.mkdir(parents=True, exist_ok=True)
        (d / "state_0x88.bin").write_bytes(kb.query(0x08))
        (d / "keymap_0x8d.bin").write_bytes(self.keymap)
        (d / "palette_0x94.bin").write_bytes(b"".join(kb.get_palette()))
        (d / "keymask_0x8e.bin").write_bytes(kb.read_key_mask())
        (d / "gamemode_0x89.bin").write_bytes(bytes([kb.get_game_mode()]))
        saved = ["state", "palette", "key mask", "game mode"]
        if (rate := kb.get_report_rate()) and (resp := kb.get_response_time()) in RESPONSE_TIMES_MS:
            (d / "usb.txt").write_text(f"report_rate={rate}\nresponse_time={resp}\n")
            saved.append("USB settings")
        for slot in range(SLOTS):
            (d / f"rgb_slot{slot}_0x92.bin").write_bytes(kb.read_rgb(slot))
        return saved + ["keymap", f"{SLOTS} RGB slots"]

    def restore(self, d: Path) -> list[str]:
        """Restore everything backed up except the keymap, which is never written."""
        kb = self.kb
        if not d.is_dir():
            raise ValueError(f"no backup at {d}")
        restored = []
        f = d / "palette_0x94.bin"
        if f.exists():
            pal = f.read_bytes()
            for i in range(len(pal) // 3):
                kb.set_palette(i, pal[3 * i:3 * i + 3])
            restored.append("palette")
        f = d / "keymask_0x8e.bin"
        if f.exists() and len(f.read_bytes()) == KEY_MASK_LEN:
            kb.write_key_mask(f.read_bytes())
            restored.append("key mask")
        f = d / "gamemode_0x89.bin"
        if f.exists():
            kb.set_game_mode(bool(f.read_bytes()[0]))
            restored.append("game mode")
        f = d / "usb.txt"
        if f.exists():
            usb = dict(line.split("=") for line in f.read_text().split())
            kb.set_report_rate(int(usb["report_rate"]))
            kb.set_response_time(int(usb["response_time"]))
            restored.append("report rate, response time")
        for slot in range(SLOTS):
            f = d / f"rgb_slot{slot}_0x92.bin"
            if f.exists():
                kb.write_rgb(slot, f.read_bytes())
                restored.append(f"slot {slot + 1}")
        state = kb.get_state()
        f = d / "state_0x88.bin"
        if f.exists():
            raw = f.read_bytes()
            state.mode, state.speed, state.brightness, state.color, state.direction = raw[3:8]
        kb.set_state(state)
        return restored + ["state"]
