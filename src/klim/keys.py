"""Key names -> HID usage codes.

Names are *positional* (US QWERTY legends): on AZERTY, "q" is the key labelled
A, "w" is Z, "semicolon" is M, etc.
"""

NAMES: dict[str, int] = {
    **{chr(ord("a") + i): 0x04 + i for i in range(26)},
    **{str((i + 1) % 10): 0x1E + i for i in range(10)},
    "enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C,
    "minus": 0x2D, "equal": 0x2E, "lbracket": 0x2F, "rbracket": 0x30,
    "backslash": 0x31, "hash": 0x32, "semicolon": 0x33, "quote": 0x34,
    "grave": 0x35, "comma": 0x36, "period": 0x37, "slash": 0x38,
    "capslock": 0x39,
    **{f"f{i + 1}": 0x3A + i for i in range(12)},
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48,
    "insert": 0x49, "home": 0x4A, "pageup": 0x4B,
    "delete": 0x4C, "end": 0x4D, "pagedown": 0x4E,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "iso": 0x64, "menu": 0x65,
    "lctrl": 0xE0, "lshift": 0xE1, "lalt": 0xE2, "lwin": 0xE3,
    "rctrl": 0xE4, "rshift": 0xE5, "ralt": 0xE6, "rwin": 0xE7,
}

ALIASES = {
    "escape": "esc", "bksp": "backspace", "caps": "capslock", "prtsc": "printscreen",
    "ins": "insert", "del": "delete", "pgup": "pageup", "pgdn": "pagedown",
    "altgr": "ralt", "lgui": "lwin", "rgui": "rwin", "ctrl": "lctrl",
    "shift": "lshift", "alt": "lalt", "win": "lwin",
}

GROUPS = {
    "wasd": ["w", "a", "s", "d"],
    "arrows": ["up", "down", "left", "right"],
    "fkeys": [f"f{i}" for i in range(1, 13)],
    "numbers": [str(i) for i in range(10)],
    "letters": [chr(ord("a") + i) for i in range(26)],
    "nav": ["insert", "home", "pageup", "delete", "end", "pagedown"],
    "mods": ["lctrl", "lshift", "lalt", "lwin", "rctrl", "rshift", "ralt", "menu"],
}


def name_of(usage: int) -> str:
    return next((n for n, u in NAMES.items() if u == usage), f"0x{usage:02x}")


def resolve(name: str) -> list[int]:
    """Return HID usages for a key name, group name, or raw '0xNN' usage."""
    n = name.strip().lower()
    if n in GROUPS:
        return [u for k in GROUPS[n] for u in resolve(k)]
    n = ALIASES.get(n, n)
    if n in NAMES:
        return [NAMES[n]]
    if n.startswith("0x"):
        return [int(n, 16)]
    raise KeyError(f"unknown key '{name}'")
