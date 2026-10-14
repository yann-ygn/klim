"""Textual interface: `klim tui` (or `klim tui --fake` without a keyboard)."""

import sys


def run(fake: bool = False, layout: str | None = None):
    from ..control import Klim
    from .app import KlimApp
    from .keymap import detect_layout

    if fake:
        from ..fake import FakeKeyboard
        kb, subtitle = FakeKeyboard(), "fake keyboard"
    else:
        from ..device import Keyboard
        try:
            kb = Keyboard()
        except RuntimeError as e:
            sys.exit(f"error: {e} (try `klim tui --fake`)")
        subtitle = "connected"
    try:
        KlimApp(Klim(kb), subtitle, layout or detect_layout()).run()
    finally:
        kb.close()
