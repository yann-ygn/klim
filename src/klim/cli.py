import argparse
import sys
from pathlib import Path

from . import keys
from .control import COLORS, DIRECTIONS, Info, Klim
from .themes import DEFAULT_GAMMA, THEMES
from .device import (BRIGHTNESS_MAX, MODE_NAMES, MODES, REPORT_RATES_HZ,
                     RESPONSE_TIMES_MS, SLOTS, SPEED_SLOWEST, Keyboard)


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
    return _int(s, 1, SPEED_SLOWEST, f"speed must be 1 (slowest) .. {SPEED_SLOWEST} (fastest)")


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


def fmt_rate(i: Info) -> str:
    return f"report_rate={i.report_rate or 'unknown '}Hz"


def fmt_disabled(names: list[str]) -> str:
    return f"disabled_keys={','.join(names) or 'none'}"


def on_off(b: bool) -> str:
    return "on" if b else "off"


def cmd_info(k: Klim, args):
    i = k.info()
    s = i.state
    color = f"{i.color_name} #{i.color_rgb.hex()}" if i.color_rgb else i.color_name
    print(f"mode={i.mode_name} (0x{s.mode:02x}) speed={i.speed}/{SPEED_SLOWEST} "
          f"brightness={s.brightness}/{BRIGHTNESS_MAX} color={color} ({s.color}) "
          f"direction={i.direction_name} ({s.direction})")
    print(f"game_mode={on_off(i.game_mode)} win_lock={on_off(i.win_lock)} {fmt_disabled(i.disabled_keys)}")
    print(f"{fmt_rate(i)} response_time={i.response_time}ms firmware={i.firmware}")


def cmd_mode(k: Klim, args):
    k.set_lighting(args.mode, args.speed, args.brightness, args.color, args.direction)
    cmd_info(k, args)


def cmd_brightness(k: Klim, args):
    k.set_lighting(brightness=args.level)
    cmd_info(k, args)


def cmd_speed(k: Klim, args):
    k.set_lighting(speed=args.level)
    cmd_info(k, args)


def cmd_palette(k: Klim, args):
    if args.reset:
        k.reset_palette()
    elif args.entry is not None:
        if args.rgb is None:
            sys.exit("error: palette needs ENTRY and RRGGBB")
        k.set_palette(args.entry, args.rgb)
    for n, rgb in enumerate(k.kb.get_palette()):
        print(f"{n + 1} {COLORS[n]:8} #{rgb.hex()}")


def cmd_rate(k: Klim, args):
    if args.hz is not None:
        k.set_report_rate(args.hz)
    print(f"report_rate={k.kb.get_report_rate() or 'unknown '}Hz")


def cmd_response(k: Klim, args):
    if args.ms is not None:
        k.set_response_time(args.ms)
    print(f"response_time={k.kb.get_response_time()}ms")


def cmd_gamemode(k: Klim, args):
    if args.state is not None:
        k.set_game_mode(args.state == "on")
    print(f"game_mode={on_off(k.kb.get_game_mode())}")


def cmd_winlock(k: Klim, args):
    if args.state is not None:
        k.set_win_lock(args.state == "on")
    print(f"win_lock={on_off(k.info().win_lock)}")


def cmd_disable(k: Klim, args):
    k.set_keys_enabled(args.keys, False)
    print(fmt_disabled(k.disabled_keys()))


def cmd_enable(k: Klim, args):
    if args.all:
        k.enable_all_keys()
    elif args.keys:
        k.set_keys_enabled(args.keys, True)
    else:
        sys.exit("error: give keys to enable, or --all")
    print(fmt_disabled(k.disabled_keys()))


def cmd_keys(k: Klim, args):
    slot = args.slot - 1 if args.slot is not None else k.default_slot()
    assignments = []
    for spec in args.assignments:
        names, _, color = spec.rpartition("=")
        if not names:
            sys.exit(f"bad assignment '{spec}', expected key[,key...]=RRGGBB")
        try:
            assignments.append((names.split(","), parse_color(color)))
        except argparse.ArgumentTypeError as e:
            sys.exit(f"error: {e}")
    k.paint_keys(slot, assignments, args.base)
    print(f"wrote custom slot {slot + 1}")


def cmd_theme(k: Klim, args):
    if args.slot is None and not args.palette:
        sys.exit("error: say what to theme: --slot N (a DIY slot) and/or --palette")
    theme = THEMES[args.name]
    k.apply_theme(theme, None if args.slot is None else args.slot - 1, args.palette, args.gamma)
    done = ([f"DIY{args.slot} (now showing)"] if args.slot else []) + (["palette"] if args.palette else [])
    print(f"applied {theme.name} to {' and '.join(done)}")


def cmd_backup(k: Klim, args):
    saved = k.backup(Path(args.dir))
    print(f"backed up {', '.join(saved)} to {Path(args.dir)}")


def cmd_restore(k: Klim, args):
    restored = k.restore(Path(args.dir))
    print(f"restored {', '.join(restored)} from {Path(args.dir)}")
    cmd_info(k, args)


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

    th = sub.add_parser("theme", help="apply a built-in theme to a DIY slot and/or the palette",
                        epilog="Themes: " + "; ".join(f"{t.name}: {t.description}"
                                                      for t in THEMES.values()))
    th.add_argument("name", choices=THEMES)
    th.add_argument("--slot", type=int, choices=range(1, SLOTS + 1), help="DIY slot to paint")
    th.add_argument("--palette", action="store_true", help="also recolor the 7 palette entries")
    th.add_argument("--gamma", type=float, default=DEFAULT_GAMMA,
                    help=f"LED gamma correction (default {DEFAULT_GAMMA}; 1 = send colors as-is)")

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

    t = sub.add_parser("tui", help="interactive terminal interface")
    t.add_argument("--fake", action="store_true", help="use a simulated keyboard")
    t.add_argument("--layout", choices=["us", "fr"], help="key legends (default: detect from Windows)")

    args = p.parse_args(argv)
    if args.cmd == "tui":
        from .tui import run
        return run(fake=args.fake, layout=args.layout)
    try:
        with Keyboard() as kb:
            k = Klim(kb)
            {"info": cmd_info, "mode": cmd_mode, "brightness": cmd_brightness, "speed": cmd_speed, "palette": cmd_palette,
             "theme": cmd_theme, "rate": cmd_rate, "response": cmd_response, "gamemode": cmd_gamemode, "winlock": cmd_winlock, "disable": cmd_disable,
             "enable": cmd_enable, "keys": cmd_keys,
             "backup": cmd_backup, "restore": cmd_restore}[args.cmd](k, args)
    except (RuntimeError, KeyError, ValueError, TimeoutError) as e:
        sys.exit(f"error: {e.args[0]}")
