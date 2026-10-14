import argparse
import sys
from pathlib import Path

from . import keys
from .device import (BRIGHTNESS_MAX, COLS, CUSTOM_MODE_BASE, DEFAULT_PALETTE, KEY_MASK_LEN,
                     MODE_NAMES, MODES, MULTICOLOR, MULTICOLOR_ONLY, REPORT_RATES_HZ,
                     RESPONSE_TIMES_MS, ROWS, SLOTS, SPEED_SLOWEST, Keyboard, key_enabled,
                     set_key_enabled, usage_to_index, usage_to_led)

WIN_KEYS = ("lwin", "rwin")
ALL_KEYS_ENABLED = bytes([0xFF, 0xFF, 0x1F] * ROWS)

# Names of the palette entries' factory colors (entries can be recolored with `klim palette`)
COLORS = ["red", "green", "yellow", "blue", "cyan", "magenta", "white", "multi"]
DIRECTIONS = ["right", "left", "up", "down"]  # which way the animation moves; 1..4 on the wire


def _int(s: str, lo: int, hi: int, msg: str) -> int:
    try:
        v = int(s, 0)
    except ValueError:
        v = None
    if v is None or not lo <= v <= hi:
        raise argparse.ArgumentTypeError(msg)
    return v


def parse_named(names: list[str], what: str):
    """Accept a name from `names` (-> 1-based index) or its number."""
    def parse(s: str) -> int:
        if s.lower() in names:
            return names.index(s.lower()) + 1
        return _int(s, 1, len(names), f"{what} must be 1..{len(names)} or one of: {', '.join(names)}")
    return parse


parse_palette = parse_named(COLORS, "color")  # 1..7 = palette entry, 8 = multicolor
parse_direction = parse_named(DIRECTIONS, "direction")


def parse_speed(s: str) -> int:
    """User-facing speed 1 (slowest) .. 10 (fastest) -> raw delay."""
    v = _int(s, 1, SPEED_SLOWEST, f"speed must be 1 (slowest) .. {SPEED_SLOWEST} (fastest)")
    return SPEED_SLOWEST + 1 - v


def parse_brightness(s: str) -> int:
    msg = f"brightness must be 0..{BRIGHTNESS_MAX} or a percentage 0%..100%"
    if s.endswith("%"):
        try:
            pct = float(s[:-1])
        except ValueError:
            pct = -1
        if not 0 <= pct <= 100:
            raise argparse.ArgumentTypeError(msg)
        s = str(round(pct * BRIGHTNESS_MAX / 100))
    return _int(s, 0, BRIGHTNESS_MAX, msg)


def parse_color(s: str) -> bytes:
    try:
        rgb = bytes.fromhex(s.lstrip("#"))
    except ValueError:
        rgb = b""
    if len(rgb) != 3:
        raise argparse.ArgumentTypeError(f"bad color '{s}', expected RRGGBB")
    return rgb


def parse_mode(s: str) -> int:
    s = s.lower().replace("custom", "diy")
    if s in MODES:
        return MODES[s]
    try:
        m = int(s, 0)
    except ValueError:
        m = None
    if m not in MODE_NAMES:
        raise argparse.ArgumentTypeError(f"mode must be one of: {', '.join(MODES)} (or its number)")
    return m


def cmd_info(kb: Keyboard, args):
    s = kb.get_state()
    name = MODE_NAMES.get(s.mode, "?")
    if 1 <= s.color < MULTICOLOR:
        color = f"{COLORS[s.color - 1]} #{kb.get_palette()[s.color - 1].hex()}"
    else:
        color = "multi" if s.color == MULTICOLOR else "?"
    direction = DIRECTIONS[s.direction - 1] if 1 <= s.direction <= len(DIRECTIONS) else "?"
    print(f"mode={name} (0x{s.mode:02x}) speed={SPEED_SLOWEST + 1 - s.speed}/{SPEED_SLOWEST} "
          f"brightness={s.brightness}/{BRIGHTNESS_MAX} color={color} ({s.color}) "
          f"direction={direction} ({s.direction})")
    disabled = disabled_keys(kb)
    win_lock = any(n in disabled for n in WIN_KEYS)
    print(f"game_mode={'on' if kb.get_game_mode() else 'off'} win_lock={'on' if win_lock else 'off'} "
          f"disabled_keys={','.join(disabled) or 'none'}")
    print(f"report_rate={kb.get_report_rate() or 'unknown '}Hz response_time={kb.get_response_time()}ms "
          f"firmware={kb.get_firmware_version()}")


def disabled_keys(kb: Keyboard) -> list[str]:
    km, mask = kb.read_keymap(), kb.read_key_mask()
    names = []
    for k in range(ROWS * COLS):
        if not key_enabled(mask, k) and km[4 * k + 2]:
            names.append(keys.name_of(km[4 * k + 2]) if km[4 * k] == 0 else f"#{k}")
    return names


def set_keys_enabled(kb: Keyboard, names: list[str], enabled: bool, strict: bool = True):
    index = usage_to_index(kb.read_keymap())
    mask = kb.read_key_mask()
    for name in names:
        for usage in keys.resolve(name):
            if usage in index:
                set_key_enabled(mask, index[usage], enabled)
            elif strict:
                sys.exit(f"key '{name}' (usage 0x{usage:02x}) not in keymap")
    kb.write_key_mask(mask)


def cmd_mode(kb: Keyboard, args):
    s = kb.get_state()
    s.mode = args.mode
    for f in ("speed", "brightness", "color", "direction"):
        if getattr(args, f) is not None:
            setattr(s, f, getattr(args, f))
    if s.mode in MULTICOLOR_ONLY:
        s.color = MULTICOLOR
    kb.set_state(s)
    cmd_info(kb, args)


def cmd_brightness(kb: Keyboard, args):
    s = kb.get_state()
    s.brightness = args.level
    kb.set_state(s)
    cmd_info(kb, args)


def cmd_speed(kb: Keyboard, args):
    s = kb.get_state()
    s.speed = args.level
    kb.set_state(s)
    cmd_info(kb, args)


def cmd_palette(kb: Keyboard, args):
    if args.reset:
        for i, rgb in enumerate(DEFAULT_PALETTE):
            kb.set_palette(i, rgb)
    elif args.entry is not None:
        if args.rgb is None:
            sys.exit("error: palette needs ENTRY and RRGGBB")
        kb.set_palette(args.entry - 1, args.rgb)
    for i, rgb in enumerate(kb.get_palette()):
        print(f"{i + 1} {COLORS[i]:8} #{rgb.hex()}")


def cmd_rate(kb: Keyboard, args):
    if args.hz is not None:
        kb.set_report_rate(args.hz)
    print(f"report_rate={kb.get_report_rate() or 'unknown '}Hz")


def cmd_response(kb: Keyboard, args):
    if args.ms is not None:
        kb.set_response_time(args.ms)
    print(f"response_time={kb.get_response_time()}ms")


def cmd_gamemode(kb: Keyboard, args):
    if args.state is not None:
        kb.set_game_mode(args.state == "on")
    print(f"game_mode={'on' if kb.get_game_mode() else 'off'}")


def cmd_winlock(kb: Keyboard, args):
    if args.state is not None:
        set_keys_enabled(kb, list(WIN_KEYS), args.state == "off", strict=False)
    win_lock = any(n in disabled_keys(kb) for n in WIN_KEYS)
    print(f"win_lock={'on' if win_lock else 'off'}")


def cmd_disable(kb: Keyboard, args):
    set_keys_enabled(kb, args.keys, False)
    print(f"disabled_keys={','.join(disabled_keys(kb)) or 'none'}")


def cmd_enable(kb: Keyboard, args):
    if args.all:
        kb.write_key_mask(ALL_KEYS_ENABLED)
    elif args.keys:
        set_keys_enabled(kb, args.keys, True)
    else:
        sys.exit("error: give keys to enable, or --all")
    print(f"disabled_keys={','.join(disabled_keys(kb)) or 'none'}")


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
        try:
            rgb = parse_color(color)
        except argparse.ArgumentTypeError as e:
            sys.exit(f"error: {e}")
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
    (d / "palette_0x94.bin").write_bytes(b"".join(kb.get_palette()))
    (d / "keymask_0x8e.bin").write_bytes(kb.read_key_mask())
    (d / "gamemode_0x89.bin").write_bytes(bytes([kb.get_game_mode()]))
    if (rate := kb.get_report_rate()) and (resp := kb.get_response_time()) in RESPONSE_TIMES_MS:
        (d / "usb.txt").write_text(f"report_rate={rate}\nresponse_time={resp}\n")
    for slot in range(SLOTS):
        (d / f"rgb_slot{slot}_0x92.bin").write_bytes(kb.read_rgb(slot))
    print(f"backed up state, palette, key mask, game mode, USB settings, keymap and "
          f"{SLOTS} RGB slots to {d}")


def cmd_restore(kb: Keyboard, args):
    """Restores everything backed up except the keymap, which is never written."""
    d = Path(args.dir)
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
    print(f"restored {', '.join(restored + ['state'])} from {d}")
    cmd_info(kb, args)


def main(argv=None):
    p = argparse.ArgumentParser(prog="klim", description="KLIM Dash TKL lighting control")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show current lighting state")

    m = sub.add_parser("mode", help=f"set lighting mode: {', '.join(MODES)}")
    m.add_argument("mode", type=parse_mode)
    m.add_argument("--speed", type=parse_speed, help=f"1 (slowest) .. {SPEED_SLOWEST} (fastest)")
    m.add_argument("--brightness", type=parse_brightness)
    m.add_argument("--color", type=parse_palette,
                   help=f"palette entry {', '.join(COLORS)} or 1..8 (see `klim palette`)")
    m.add_argument("--direction", type=parse_direction, help=f"{', '.join(DIRECTIONS)} or 1..4")

    br = sub.add_parser("brightness", help=f"set brightness (0..{BRIGHTNESS_MAX}, or e.g. 50%%)")
    br.add_argument("level", type=parse_brightness)

    sp = sub.add_parser("speed", help=f"set animation speed (1 slowest .. {SPEED_SLOWEST} fastest)")
    sp.add_argument("level", type=parse_speed)

    pa = sub.add_parser("palette", help="list or recolor the 7 palette entries used by --color")
    pa.add_argument("entry", nargs="?", type=parse_named(COLORS[:-1], "entry"))
    pa.add_argument("rgb", nargs="?", type=parse_color, metavar="RRGGBB")
    pa.add_argument("--reset", action="store_true", help="restore factory colors")

    ra = sub.add_parser("rate", help="show or set USB report (polling) rate")
    ra.add_argument("hz", nargs="?", type=int, choices=REPORT_RATES_HZ)
    rs = sub.add_parser("response", help="show or set response time (key debounce) in ms")
    rs.add_argument("ms", nargs="?", type=int, choices=RESPONSE_TIMES_MS)

    on_off = dict(nargs="?", choices=["on", "off"])
    g = sub.add_parser("gamemode", help="show or set game mode (lights Print Screen white)")
    g.add_argument("state", **on_off)
    w = sub.add_parser("winlock", help="show or set Win key lock")
    w.add_argument("state", **on_off)
    dis = sub.add_parser("disable", help="disable keys, e.g. capslock lwin")
    dis.add_argument("keys", nargs="+", metavar="KEY")
    en = sub.add_parser("enable", help="re-enable keys disabled with `klim disable`")
    en.add_argument("keys", nargs="*", metavar="KEY")
    en.add_argument("--all", action="store_true", help="enable every key")

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
            {"info": cmd_info, "mode": cmd_mode, "brightness": cmd_brightness, "speed": cmd_speed, "palette": cmd_palette,
             "rate": cmd_rate, "response": cmd_response, "gamemode": cmd_gamemode, "winlock": cmd_winlock, "disable": cmd_disable,
             "enable": cmd_enable, "keys": cmd_keys,
             "backup": cmd_backup, "restore": cmd_restore}[args.cmd](kb, args)
    except (RuntimeError, KeyError, TimeoutError) as e:
        sys.exit(f"error: {e.args[0]}")
