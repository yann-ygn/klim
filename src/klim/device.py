"""Low-level protocol for the KLIM Dash TKL (Holtek 04D9:A231).

Every command is a 9-byte feature report on interface 3:

    [0x00] CMD b2 b3 COUNT b5 b6 b7 CHK      CHK = 0xFF - sum(CMD..b7)

Writes have bit 7 clear; the matching read is CMD | 0x80 (set feature, then
get feature). Bulk payloads are COUNT x 64-byte output/input reports.
"""

import time
from dataclasses import dataclass

import hid

VID, PID, INTERFACE = 0x04D9, 0xA231, 3

CMD_STATE = 0x08
CMD_KEYMAP = 0x0D
CMD_RGB = 0x12
READ = 0x80

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
MULTICOLOR = 8  # color value; palette entries are 1..7
MULTICOLOR_ONLY = (0x03, 0x08, 0x0A)  # wave, spectrum, raindrop

ROWS, COLS = 6, 21
ENTRIES = 128


def keymap_to_led(k: int) -> int:
    """Keymap is row-major (bottom row first), LEDs are column-major."""
    return (k % COLS) * ROWS + k // COLS


@dataclass
class State:
    mode: int
    speed: int  # raw delay, SPEED_SLOWEST (10) .. SPEED_FASTEST (1)
    brightness: int  # 0 (off) .. BRIGHTNESS_MAX
    color: int  # 8 = multicolor, 1 = red
    direction: int

    def as_bytes(self) -> list[int]:
        return [self.mode, self.speed, self.brightness, self.color, self.direction]


class Keyboard:
    def __init__(self):
        info = next((d for d in hid.enumerate(VID, PID) if d["interface_number"] == INTERFACE), None)
        if info is None:
            raise RuntimeError(f"KLIM Dash TKL ({VID:04X}:{PID:04X}) not found")
        self.dev = hid.device()
        self.dev.open_path(info["path"])

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


def usage_to_led(keymap: bytes) -> dict[int, int]:
    """Map HID usage -> LED index for standard (type 0) keymap entries."""
    out = {}
    for k in range(ROWS * COLS):
        typ, usage = keymap[4 * k], keymap[4 * k + 2]
        if typ == 0 and usage:
            out.setdefault(usage, keymap_to_led(k))
    return out
