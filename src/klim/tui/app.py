import queue
import threading
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import (Button, Footer, Header, Input, Label, OptionList, RadioButton,
                             RadioSet, TabbedContent, TabPane)
from textual.widgets.option_list import Option

from ..control import COLORS, DIRECTIONS, Info, Klim
from ..device import (BRIGHTNESS_MAX, CUSTOM_MODE_BASE, MODES, MULTICOLOR, MULTICOLOR_ONLY,
                      SPEED_SLOWEST, State)
from .widgets import Slider, Swatch

DEBOUNCE = 0.15  # seconds; sliders only write once they settle
ARROWS = {"right": "→", "left": "←", "up": "↑", "down": "↓"}


class DeviceThread:
    """Runs keyboard calls one at a time, in order, off the UI thread."""

    def __init__(self, app: App, klim: Klim):
        self.app, self.klim = app, klim
        self.queue: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="klim-device", daemon=True)
        self.thread.start()

    def submit(self, fn: Callable[[Klim], object], on_done: Callable[[object], None] | None = None):
        self.queue.put((fn, on_done))

    @property
    def busy(self) -> bool:
        return self.queue.unfinished_tasks > 0

    def stop(self):
        self.queue.put((None, None))
        self.thread.join(timeout=2)

    def _run(self):
        while True:
            fn, on_done = self.queue.get()
            try:
                if fn is None:
                    return
                try:
                    result = fn(self.klim)
                except Exception as e:  # report and keep serving
                    self._call(self.app.device_error, e)
                    continue
                if on_done is not None:
                    self._call(on_done, result)
            finally:
                self.queue.task_done()

    def _call(self, callback, *args):
        try:
            self.app.call_from_thread(callback, *args)
        except RuntimeError:  # app already shut down
            pass


def mode_label(name: str) -> str:
    return name.upper() if name.startswith("diy") else name.capitalize()


class LightingPane(TabPane):
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
            self.app.device.submit(lambda k: k.reset_palette(), lambda _: self.app.refresh_info())

    def recolor(self):
        text = self.query_one("#palette-hex", Input).value.strip().lstrip("#")
        try:
            rgb = bytes.fromhex(text)
            assert len(rgb) == 3
        except (ValueError, AssertionError):
            self.app.notify(f"'{text}' is not a #rrggbb color", severity="error")
            return
        entry = self.app.info.state.color
        self.app.device.submit(lambda k: k.set_palette(entry, rgb), lambda _: self.app.refresh_info())


class KlimApp(App):
    TITLE = "KLIM Dash TKL"
    BINDINGS = [
        Binding("r", "refresh", "Reload from keyboard"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, klim: Klim, subtitle: str = ""):
        super().__init__()
        self.klim = klim
        self.sub_title = subtitle
        self.info: Info | None = None
        self.device: DeviceThread | None = None
        self._debounce_timers: dict[str, Timer] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            yield LightingPane("Lighting", id="lighting")
        yield Footer()

    def on_mount(self):
        self.device = DeviceThread(self, self.klim)
        self.refresh_info()

    def on_unmount(self):
        if self.device:
            self.device.stop()

    # --- device plumbing --------------------------------------------------

    def refresh_info(self):
        self.device.submit(lambda k: k.info(), self.show_info)

    def show_info(self, info: Info):
        self.info = info
        self.sub_title = f"{self.sub_title.split(' · ')[0]} · firmware {info.firmware}"
        self.query_one(LightingPane).show(info)

    def apply_lighting(self, **changes):
        def done(state: State):
            self.info.state = state
            self.query_one(LightingPane).show(self.info)
        self.device.submit(lambda k: k.set_lighting(**changes), done)

    def debounce(self, key: str, fn: Callable[[], None]):
        """Run fn once `key` has had no new calls for DEBOUNCE seconds."""
        if timer := self._debounce_timers.pop(key, None):
            timer.stop()

        def fire():
            self._debounce_timers.pop(key, None)
            fn()
        self._debounce_timers[key] = self.set_timer(DEBOUNCE, fire)

    @property
    def busy(self) -> bool:
        """True while changes are waiting to be debounced or sent."""
        return bool(self._debounce_timers) or self.device.busy

    def device_error(self, error: Exception):
        self.notify(f"{type(error).__name__}: {error}", title="Keyboard error", severity="error")

    def action_refresh(self):
        self.refresh_info()
