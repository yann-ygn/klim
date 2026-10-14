"""In-memory stand-in for `device.Keyboard`, for tests and `klim tui --fake`.

Mirrors the observed firmware behaviour, including its quirks: values are
stored without range checks and Constant mode forces multicolor to red.
"""

import copy

from .device import DEFAULT_PALETTE, KEY_MASK_LEN, REPORT_RATES_HZ, State

# Factory keymap read from a real KLIM Dash TKL (0x8D), 128 x [type, mod, usage, 0]
KEYMAP = bytes.fromhex(
    "0000e0000000e3000000e2000000910000008b0000002c0000008a0000009000000088000000e6000200000000006500"
    "0000e6000000e400000050000000510000004f000000620000e01e0000006300000058000000e10000001d0000001b00"
    "0000060000001900000005000000110000001000000036000000370000003800000087000000e5000000890004010400"
    "00005200000000000000590000005a0000005b0000000000000039000000040000001600000007000000090000000a00"
    "00000b0000000d0000000e0000000f000000330000003400000031000000280000e0210000e022000000000000005c00"
    "00005d0000005e000000570000002b000000140000001a0000000800000015000000170000001c000000180000000c00"
    "000012000000130000002f00000030000000310000004c0000004d0000004e0000005f00000060000000610000e02000"
    "0000350000001e0000001f00000020000000210000002200000023000000240000002500000026000000270000002d00"
    "00002e0000002a000000490000004a0000004b0000005300000054000000550000005600000029000000640000003a00"
    "00003b0000003c0000003d0000003e0000003f0000004000000041000000420000004300000044000000450000004600"
    "00004700000048000300ea0000000000000000000300e9000000000000000000"
)
assert len(KEYMAP) == 512


class FakeKeyboard:
    def __init__(self):
        self.state = State(mode=0x01, speed=6, brightness=36, color=1, direction=1)
        self.palette = list(DEFAULT_PALETTE)
        self.game_mode = False
        self.key_mask = bytearray([0xFF, 0xFF, 0x1F] * (KEY_MASK_LEN // 3))
        self.rgb = [bytearray(512) for _ in range(5)]
        self.report_rate = 3
        self.response = 4
        self.writes = 0  # number of write commands, to check debouncing

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def query(self, cmd: int, *args: int) -> bytes:
        assert cmd == 0x08, "only the state query is used directly"
        return bytes([0, 0x88, 0, *self.state.as_bytes(), 0])

    def get_state(self) -> State:
        return copy.copy(self.state)

    def set_state(self, state: State):
        self.writes += 1
        self.state = copy.copy(state)
        if self.state.mode == 0x01 and self.state.color == 8:
            self.state.color = 1

    def get_palette(self) -> list[bytes]:
        return list(self.palette)

    def set_palette(self, index: int, rgb: bytes):
        self.writes += 1
        self.palette[index] = bytes(rgb)

    def get_firmware_version(self) -> str:
        return "1.2"

    def get_report_rate(self) -> int | None:
        r = self.report_rate
        return REPORT_RATES_HZ[r] if r < len(REPORT_RATES_HZ) else None

    def set_report_rate(self, hz: int):
        self.writes += 1
        self.report_rate = REPORT_RATES_HZ.index(hz)

    def get_response_time(self) -> int:
        return self.response * 2

    def set_response_time(self, ms: int):
        self.writes += 1
        self.response = ms // 2

    def get_game_mode(self) -> bool:
        return self.game_mode

    def set_game_mode(self, on: bool):
        self.writes += 1
        self.game_mode = on

    def read_key_mask(self) -> bytearray:
        return bytearray(self.key_mask)

    def write_key_mask(self, mask: bytes):
        self.writes += 1
        self.key_mask = bytearray(mask)

    def read_rgb(self, slot: int) -> bytearray:
        return bytearray(self.rgb[slot])

    def write_rgb(self, slot: int, data: bytes):
        self.writes += 1
        self.rgb[slot] = bytearray(data)
        for led in (126, 127):  # the firmware does not keep these
            self.rgb[slot][4 * led:4 * led + 4] = b"\0\0\0\0"

    def read_keymap(self) -> bytes:
        return KEYMAP
