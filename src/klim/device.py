"""Low-level protocol for the KLIM Dash TKL (Holtek 04D9:A231).

Every command is a 9-byte feature report on interface 3:

    [0x00] CMD b2 b3 COUNT b5 b6 b7 CHK      CHK = 0xFF - sum(CMD..b7)

Writes have bit 7 clear; the matching read is CMD | 0x80 (set feature, then
get feature). Bulk payloads are COUNT x 64-byte output/input reports.
"""

import sys
import time
from dataclasses import dataclass

import hid

VID, PID, INTERFACE = 0x04D9, 0xA231, 3

CMD_VERSION = 0x00  # read-only (0x80)
CMD_REPORT_RATE = 0x01
CMD_RESPONSE_TIME = 0x04
CMD_STATE = 0x08
CMD_GAME_MODE = 0x09
CMD_KEYMAP = 0x0D
CMD_KEY_MASK = 0x0E
CMD_RGB = 0x12
CMD_PALETTE = 0x14
READ = 0x80
# 0x13 0xFF is sent by the vendor app before re-reading everything: most likely a
# factory reset. Never send it.

SLOTS = 5
BRIGHTNESS_MAX = 50  # 0 = LEDs off
SPEED_SLOWEST, SPEED_FASTEST = 10, 1  # raw values: speed is an animation delay
CUSTOM_MODE_BASE = 0x33  # modes 0x33..0x37 display RGB slots 0..4
MODES = {
    "constant": 0x01, "breathing": 0x02, "wave": 0x03, "reactive": 0x04,
    "chase": 0x05, "ripple": 0x06, "spectrum": 0x08, "raindrop": 0x0A,
    "vortex": 0x0B, "spotlight": 0x0C, "radar": 0x0D,
    **{f"diy{i + 1}": CUSTOM_MODE_BASE + i for i in range(SLOTS)},
}
MODE_NAMES = {v: k for k, v in MODES.items()}
MULTICOLOR = 8  # color value; 1..7 select palette entries 0..6
DEFAULT_PALETTE = [bytes.fromhex(c) for c in
                   ("ff0000", "00ff00", "ffff00", "0000ff", "00ffff", "ff00ff", "ffffff")]
MULTICOLOR_ONLY = (0x03, 0x08, 0x0A)  # wave, spectrum, raindrop

# The firmware stores any value for these, so callers must stay within range.
REPORT_RATES_HZ = (125, 250, 500, 1000)  # wire value = index
RESPONSE_TIMES_MS = tuple(range(2, 21, 2))  # wire value = ms / 2 (debounce)

ROWS, COLS = 6, 21
ENTRIES = 128
KEY_MASK_LEN = ROWS * 3  # one little-endian 21-bit column mask per row, 1 = key enabled


def keymap_to_led(k: int) -> int:
    """Keymap is row-major (bottom row first), LEDs are column-major."""
    return (k % COLS) * ROWS + k // COLS


@dataclass
class State:
    mode: int
    speed: int  # raw delay, SPEED_SLOWEST (10) .. SPEED_FASTEST (1)
    brightness: int  # 0 (off) .. BRIGHTNESS_MAX
    color: int  # 1..7 = palette entry 0..6, 8 = multicolor
    direction: int

    def as_bytes(self) -> list[int]:
        return [self.mode, self.speed, self.brightness, self.color, self.direction]


class Keyboard:
    def __init__(self):
        info = next((d for d in hid.enumerate(VID, PID) if d["interface_number"] == INTERFACE), None)
        if info is None:
            raise RuntimeError(f"KLIM Dash TKL ({VID:04X}:{PID:04X}) not found")
        self.dev = hid.device()
        try:
            self.dev.open_path(info["path"])
        except OSError as e:
            path = info["path"].decode(errors="replace")
            hint = (" Add the udev rule from linux/70-klim-dash-tkl.rules (see README) and replug."
                    if sys.platform.startswith("linux") else "")
            raise RuntimeError(f"found the keyboard but could not open {path} ({e}).{hint}") from e

    def close(self):
        self.dev.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def command(self, *payload: int):
        b = list(payload) + [0] * (7 - len(payload))
        b.append((0xFF - sum(b)) & 0xFF)
        self.dev.send_feature_report([0] + b)

    def query(self, cmd: int, *args: int) -> bytes:
        self.command(cmd | READ, *args)
        time.sleep(0.02)
        return bytes(self.dev.get_feature_report(0, 9))

    def _drain(self):
        self.dev.set_nonblocking(1)
        while self.dev.read(65):
            pass
        self.dev.set_nonblocking(0)

    def _read_bulk(self, cmd: int, arg: int = 0, count: int = 8) -> bytes:
        self._drain()
        self.command(cmd | READ, 0, arg, count if cmd != CMD_KEYMAP else 0)
        time.sleep(0.005)
        self.dev.get_feature_report(0, 9)
        data = b""
        for _ in range(count):
            pkt = bytes(self.dev.read(65, 1000))
            if len(pkt) < 64:
                raise TimeoutError("short read from keyboard")
            data += pkt[-64:]
        return data

    def _write_bulk(self, cmd: int, arg: int, data: bytes):
        count = len(data) // 64
        self.command(cmd, 0, arg, count)
        time.sleep(0.005)
        for i in range(0, len(data), 64):
            self.dev.write([0] + list(data[i:i + 64]))
            time.sleep(0.005)

    # --- lighting state -------------------------------------------------

    def get_state(self) -> State:
        r = self.query(CMD_STATE)
        return State(*r[3:8])

    def set_state(self, state: State):
        """Apply a lighting state. Also makes freshly uploaded RGB slots visible."""
        self.command(CMD_STATE, 0x02, *state.as_bytes())
        time.sleep(0.02)

    # --- palette (takes effect immediately) ----------------------------

    def get_palette(self) -> list[bytes]:
        return [self.query(CMD_PALETTE, 0, n)[4:7] for n in range(len(DEFAULT_PALETTE))]

    def set_palette(self, index: int, rgb: bytes):
        self.command(CMD_PALETTE, 0, index, *rgb)
        time.sleep(0.02)

    def get_firmware_version(self) -> str:
        r = self.query(CMD_VERSION)
        return f"{r[3]}.{r[2]}"

    # --- USB report rate / response time -------------------------------

    def get_report_rate(self) -> int | None:
        """Polling rate in Hz, or None if the keyboard holds an out-of-range value."""
        v = self.query(CMD_REPORT_RATE)[2]
        return REPORT_RATES_HZ[v] if v < len(REPORT_RATES_HZ) else None

    def set_report_rate(self, hz: int):
        self.command(CMD_REPORT_RATE, REPORT_RATES_HZ.index(hz))
        time.sleep(0.02)

    def get_response_time(self) -> int:
        """Debounce in ms."""
        return self.query(CMD_RESPONSE_TIME)[2] * 2

    def set_response_time(self, ms: int):
        if ms not in RESPONSE_TIMES_MS:
            raise ValueError(f"response time must be one of {RESPONSE_TIMES_MS}")
        self.command(CMD_RESPONSE_TIME, ms // 2)
        time.sleep(0.02)

    # --- game mode / key enable mask -----------------------------------

    def get_game_mode(self) -> bool:
        return bool(self.query(CMD_GAME_MODE)[2])

    def set_game_mode(self, on: bool):
        self.command(CMD_GAME_MODE, int(on))
        time.sleep(0.02)

    def read_key_mask(self) -> bytearray:
        """18 bytes, rows bottom-first like the keymap; a cleared bit disables that key."""
        self._drain()
        self.command(CMD_KEY_MASK | READ, 0, 0, KEY_MASK_LEN)
        time.sleep(0.01)
        self.dev.get_feature_report(0, 9)
        pkt = bytes(self.dev.read(65, 1000))
        if len(pkt) < 64:
            raise TimeoutError("short read from keyboard")
        return bytearray(pkt[-64:][:KEY_MASK_LEN])

    def write_key_mask(self, mask: bytes):
        assert len(mask) == KEY_MASK_LEN
        self.command(CMD_KEY_MASK, 0, 0, KEY_MASK_LEN)
        time.sleep(0.01)
        self.dev.write([0] + list(mask) + [0] * (64 - KEY_MASK_LEN))
        time.sleep(0.02)

    # --- per-key RGB ----------------------------------------------------

    def read_rgb(self, slot: int) -> bytearray:
        """512 bytes: 128 x [0, R, G, B], indexed by LED number."""
        return bytearray(self._read_bulk(CMD_RGB, slot))

    def write_rgb(self, slot: int, data: bytes):
        assert len(data) == 512
        self._write_bulk(CMD_RGB, slot, bytes(data))

    # --- keymap (read-only for now) -------------------------------------

    def read_keymap(self) -> bytes:
        """512 bytes: 128 x [type, modifier, HID usage, 0], row-major, bottom row first."""
        return self._read_bulk(CMD_KEYMAP)


def usage_to_index(keymap: bytes) -> dict[int, int]:
    """Map HID usage -> keymap index for standard (type 0) keymap entries.

    Plain entries win over ones carrying a modifier: the factory keymap also
    has Ctrl+1/3/4/5 entries at grid positions with no physical key.
    """
    out = {}
    for plain in (True, False):
        for k in range(ROWS * COLS):
            typ, mod, usage = keymap[4 * k], keymap[4 * k + 1], keymap[4 * k + 2]
            if typ == 0 and usage and (mod == 0) == plain:
                out.setdefault(usage, k)
    return out


def usage_to_led(keymap: bytes) -> dict[int, int]:
    """Map HID usage -> LED index."""
    return {u: keymap_to_led(k) for u, k in usage_to_index(keymap).items()}


def _mask_bit(k: int) -> tuple[int, int]:
    """Keymap index -> (byte offset, bit) in the key enable mask."""
    col = k % COLS
    return 3 * (k // COLS) + col // 8, 1 << (col % 8)


def key_enabled(mask: bytes, k: int) -> bool:
    i, bit = _mask_bit(k)
    return bool(mask[i] & bit)


def set_key_enabled(mask: bytearray, k: int, enabled: bool):
    i, bit = _mask_bit(k)
    mask[i] = mask[i] | bit if enabled else mask[i] & ~bit
