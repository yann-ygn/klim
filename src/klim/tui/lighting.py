from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, OptionList, RadioButton, RadioSet
from textual.widgets.option_list import Option

from ..control import COLORS, DIRECTIONS, Info
from ..device import (BRIGHTNESS_MAX, CUSTOM_MODE_BASE, MODES, MULTICOLOR, MULTICOLOR_ONLY,
                      SPEED_SLOWEST)
from .pane import Pane
from .widgets import Slider, Swatch

ARROWS = {"right": "→", "left": "←", "up": "↑", "down": "↓"}


def mode_label(name: str) -> str:
    return name.upper() if name.startswith("diy") else name.capitalize()


class LightingPane(Pane):
    DEFAULT_CSS = """
    LightingPane > Horizontal { height: 1fr; }
    LightingPane #modes { width: 22; height: 1fr; }
    LightingPane #controls { padding: 0 2; height: auto; }
    LightingPane .field { margin-top: 1; color: $text-muted; }
    LightingPane #swatches { height: 4; }
    LightingPane #palette-edit Button { margin-left: 1; }
    LightingPane #palette-edit { height: 3; margin-top: 1; }
    LightingPane #palette-hex { width: 14; }
    LightingPane #directions { layout: horizontal; width: auto; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="modes"):
                yield Label("Mode", classes="field")
                yield OptionList(*(Option(mode_label(n), id=n) for n in MODES), id="mode-list")
            with Vertical(id="controls"):
                yield Label("Speed", classes="field")
                yield Slider(1, SPEED_SLOWEST, id="speed", fmt=lambda v: f"{v}/{SPEED_SLOWEST}")
                yield Label("Brightness", classes="field")
                yield Slider(0, BRIGHTNESS_MAX, id="brightness",
                             fmt=lambda v: f"{round(v * 100 / BRIGHTNESS_MAX)}%")
                yield Label("Color", classes="field")
                with Horizontal(id="swatches"):
                    for i, name in enumerate(COLORS):
                        yield Swatch(i + 1, None if i + 1 == MULTICOLOR else b"\0\0\0",
                                     tooltip=f"palette entry {i + 1} ({name})" if i + 1 < MULTICOLOR
                                     else "multicolor")
                with Horizontal(id="palette-edit"):
                    yield Input(placeholder="#rrggbb", id="palette-hex", max_length=7)
                    yield Button("Recolor", id="palette-set")
                    yield Button("Reset palette", id="palette-reset")
                yield Label("Direction", classes="field")
                with RadioSet(id="directions"):
                    for name in DIRECTIONS:
                        yield RadioButton(f"{ARROWS[name]} {name}", id=f"dir-{name}")

    # --- keyboard -> UI ---------------------------------------------------

    def show(self, info: Info):
        s = info.state
        with self.app.prevent(Slider.Changed, OptionList.OptionHighlighted, RadioSet.Changed,
                              RadioButton.Changed, Input.Changed):
            modes = list(MODES.values())
            if s.mode in modes:
                self.query_one("#mode-list", OptionList).highlighted = modes.index(s.mode)
            self.query_one("#speed", Slider).value = info.speed
            self.query_one("#brightness", Slider).value = s.brightness
            for swatch in self.query(Swatch):
                if swatch.index < MULTICOLOR:
                    swatch.rgb = info.palette[swatch.index - 1]
                swatch.selected = swatch.index == s.color
                swatch.disabled = s.mode in MULTICOLOR_ONLY or s.mode >= CUSTOM_MODE_BASE
            if 1 <= s.direction <= len(DIRECTIONS):
                self.query_one(f"#dir-{DIRECTIONS[s.direction - 1]}", RadioButton).value = True
            rgb = info.color_rgb
            self.query_one("#palette-hex", Input).value = f"#{rgb.hex()}" if rgb else ""
        self.query_one("#palette-hex", Input).disabled = info.color_rgb is None
        self.query_one("#palette-set", Button).disabled = info.color_rgb is None

    # --- UI -> keyboard ---------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.app.apply_lighting(mode=MODES[event.option.id])

    def on_slider_changed(self, event: Slider.Changed):
        self.app.debounce(event.slider.id, lambda: self.app.apply_lighting(
            **{event.slider.id: event.slider.value}))

    def on_swatch_selected(self, event: Swatch.Selected):
        self.app.apply_lighting(color=event.swatch.index)

    def on_radio_set_changed(self, event: RadioSet.Changed):
        self.app.apply_lighting(direction=event.index + 1)

    def on_input_submitted(self, event: Input.Submitted):
        self.recolor()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "palette-set":
            self.recolor()
        elif event.button.id == "palette-reset":
            self.app.change(lambda k: k.reset_palette())

    def recolor(self):
        text = self.query_one("#palette-hex", Input).value.strip().lstrip("#")
        try:
            rgb = bytes.fromhex(text)
            assert len(rgb) == 3
        except (ValueError, AssertionError):
            self.app.notify(f"'{text}' is not a #rrggbb color", severity="error")
            return
        entry = self.app.info.state.color
        self.app.change(lambda k: k.set_palette(entry, rgb))
