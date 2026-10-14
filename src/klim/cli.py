import argparse
import sys
from pathlib import Path

from . import keys
from .device import BRIGHTNESS_MAX, CUSTOM_MODE_BASE, MODES, SLOTS, Keyboard, usage_to_led


def parse_int(s: str) -> int:
    return int(s, 0)


def parse_brightness(s: str) -> int:
    v = round(float(s[:-1]) * BRIGHTNESS_MAX / 100) if s.endswith("%") else int(s, 0)
    if not 0 <= v <= BRIGHTNESS_MAX:
        raise argparse.ArgumentTypeError(f"brightness must be 0..{BRIGHTNESS_MAX} or a percentage")
    return v


def parse_color(s: str) -> bytes:
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError(f"bad color '{s}', expected RRGGBB")
    return bytes.fromhex(s)


def parse_mode(s: str) -> int:
    s = s.lower()
    if s.startswith("custom"):
        slot = int(s[6:] or 1) - 1
        if not 0 <= slot < SLOTS:
            raise argparse.ArgumentTypeError(f"custom slot must be 1..{SLOTS}")
        return CUSTOM_MODE_BASE + slot
    m = int(s, 0)
    if m not in MODES:
        raise argparse.ArgumentTypeError(f"mode must be one of {', '.join(f'0x{x:02x}' for x in MODES)}")
    return m


def cmd_info(kb: Keyboard, args):
    s = kb.get_state()
    slot = f" (custom slot {s.mode - CUSTOM_MODE_BASE + 1})" if s.mode >= CUSTOM_MODE_BASE else ""
    print(f"mode=0x{s.mode:02x}{slot} speed={s.speed} brightness={s.brightness}/{BRIGHTNESS_MAX} "
          f"color={s.color} direction={s.direction}")


def cmd_mode(kb: Keyboard, args):
    s = kb.get_state()
    s.mode = args.mode
    for f in ("speed", "brightness", "color", "direction"):
        if getattr(args, f) is not None:
            setattr(s, f, getattr(args, f))
    kb.set_state(s)
    cmd_info(kb, args)


def cmd_brightness(kb: Keyboard, args):
    s = kb.get_state()
    s.brightness = args.level
    kb.set_state(s)
    cmd_info(kb, args)


def cmd_keys(kb: Keyboard, args):
    state = kb.get_state()
    if args.slot is not None:
        slot = args.slot - 1
    elif state.mode >= CUSTOM_MODE_BASE:
        slot = state.mode - CUSTOM_MODE_BASE
    else:
        slot = 0

    if args.base is not None:
        buf = bytearray(512)
        for i in range(126):
            buf[4 * i + 1:4 * i + 4] = args.base
    else:
        buf = kb.read_rgb(slot)

    led = usage_to_led(kb.read_keymap())
    for spec in args.assignments:
        names, _, color = spec.rpartition("=")
        if not names:
            sys.exit(f"bad assignment '{spec}', expected key[,key...]=RRGGBB")
        rgb = parse_color(color)
        for name in names.split(","):
            for usage in keys.resolve(name):
                if usage not in led:
                    sys.exit(f"key '{name}' (usage 0x{usage:02x}) not in keymap")
                buf[4 * led[usage] + 1:4 * led[usage] + 4] = rgb

    kb.write_rgb(slot, buf)
    state.mode = CUSTOM_MODE_BASE + slot
    kb.set_state(state)
    print(f"wrote custom slot {slot + 1}")


def cmd_backup(kb: Keyboard, args):
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "state_0x88.bin").write_bytes(kb.query(0x08))
    (d / "keymap_0x8d.bin").write_bytes(kb.read_keymap())
    for slot in range(SLOTS):
        (d / f"rgb_slot{slot}_0x92.bin").write_bytes(kb.read_rgb(slot))
    print(f"backed up state, keymap and {SLOTS} RGB slots to {d}")


def cmd_restore(kb: Keyboard, args):
    """Restores lighting only (state + RGB slots); the keymap is never written."""
    d = Path(args.dir)
    restored = []
    for slot in range(SLOTS):
        f = d / f"rgb_slot{slot}_0x92.bin"
        if f.exists():
            kb.write_rgb(slot, f.read_bytes())
            restored.append(str(slot + 1))
    state = kb.get_state()
    f = d / "state_0x88.bin"
    if f.exists():
        raw = f.read_bytes()
        state.mode, state.speed, state.brightness, state.color, state.direction = raw[3:8]
    kb.set_state(state)
    print(f"restored slots [{', '.join(restored)}] and state from {d}")
    cmd_info(kb, args)


def main(argv=None):
    p = argparse.ArgumentParser(prog="klim", description="KLIM Dash TKL lighting control")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show current lighting state")

    m = sub.add_parser("mode", help="set lighting mode (0x01..0x0d, or custom1..custom5)")
    m.add_argument("mode", type=parse_mode)
    m.add_argument("--speed", type=parse_int)
    m.add_argument("--brightness", type=parse_brightness)
    m.add_argument("--color", type=parse_int)
    m.add_argument("--direction", type=parse_int)

    br = sub.add_parser("brightness", help=f"set brightness (0..{BRIGHTNESS_MAX}, or e.g. 50%%)")
    br.add_argument("level", type=parse_brightness)

    k = sub.add_parser("keys", help="set per-key colors, e.g. esc=ff0000 wasd=00ff00",
                       epilog="Key names are positional US-QWERTY (AZERTY 'A' is 'q'). "
                              f"Groups: {', '.join(keys.GROUPS)}.")
    k.add_argument("assignments", nargs="*", metavar="KEY[,KEY...]=RRGGBB")
    k.add_argument("--slot", type=int, choices=range(1, SLOTS + 1),
                   help="custom slot (default: active one, else 1)")
    k.add_argument("--base", type=parse_color, metavar="RRGGBB",
                   help="start from this color on every key instead of the slot's current colors")

    b = sub.add_parser("backup", help="save state, keymap and all RGB slots")
    b.add_argument("dir")
    r = sub.add_parser("restore", help="restore state and RGB slots from a backup")
    r.add_argument("dir")

    args = p.parse_args(argv)
    try:
        with Keyboard() as kb:
            {"info": cmd_info, "mode": cmd_mode, "brightness": cmd_brightness, "keys": cmd_keys,
             "backup": cmd_backup, "restore": cmd_restore}[args.cmd](kb, args)
    except (RuntimeError, KeyError, TimeoutError) as e:
        sys.exit(f"error: {e.args[0]}")
