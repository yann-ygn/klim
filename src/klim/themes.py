"""Built-in color themes: a 7-entry palette and a per-key layout.

Colors are given as they look on screen; `to_led` gamma-corrects them since
LED brightness is linear (sent as-is, pastels wash out to near white).
"""

from dataclasses import dataclass

DEFAULT_GAMMA = 2.2


@dataclass(frozen=True)
class Theme:
    name: str
    description: str
    palette: tuple[str, ...]  # palette entries 1..7 (red, green, yellow, blue, cyan, magenta, white slots)
    base: str  # keys not listed in `keys`
    keys: tuple[tuple[str, tuple[str, ...]], ...]  # (color, key names/groups), applied in order


def to_led(hex_color: str, gamma: float = DEFAULT_GAMMA) -> bytes:
    return bytes(round((v / 255) ** gamma * 255) for v in bytes.fromhex(hex_color.lstrip("#")))


_DRACULA = dict(purple="bd93f9", green="50fa7b", cyan="8be9fd", pink="ff79c6", orange="ffb86c",
                yellow="f1fa8c", red="ff5555", comment="6272a4")

THEMES = {
    "dracula": Theme(
        name="dracula",
        description="Dracula (draculatheme.com): purple letters, green numbers, cyan F-row, "
                    "pink modifiers, orange Enter/Backspace/arrows, yellow nav, red Esc",
        palette=tuple(_DRACULA[c] for c in ("red", "green", "yellow", "purple", "cyan", "pink",
                                            "orange")),
        base=_DRACULA["comment"],
        keys=(
            (_DRACULA["purple"], ("letters", "lbracket", "rbracket", "semicolon", "quote",
                                  "backslash", "comma", "period", "slash", "iso")),
            (_DRACULA["green"], ("grave", "numbers", "minus", "equal")),
            (_DRACULA["cyan"], ("fkeys",)),
            (_DRACULA["pink"], ("tab", "capslock", "lshift", "rshift", "lctrl", "rctrl", "lwin",
                                "lalt", "ralt", "menu", "fn")),
            (_DRACULA["orange"], ("enter", "backspace", "arrows")),
            (_DRACULA["yellow"], ("nav",)),
            (_DRACULA["red"], ("esc",)),
            (_DRACULA["comment"], ("space", "printscreen", "scrolllock", "pause")),
        ),
    ),
}
