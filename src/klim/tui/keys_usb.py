from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Label, RadioButton, RadioSet, Switch

from ..control import Info
from ..device import REPORT_RATES_HZ, RESPONSE_TIMES_MS
from .keymap import KeyboardMap
from .pane import Pane
from .widgets import Slider

ENABLED, DISABLED = bytes.fromhex("303038"), bytes.fromhex("a01818")


class KeysUsbPane(Pane):
    DEFAULT_CSS = """
    KeysUsbPane > VerticalScroll { padding: 0 2; }
    KeysUsbPane #disable-map { margin-top: 1; }
    KeysUsbPane .section { margin-top: 1; text-style: bold; }
    KeysUsbPane .field { margin-top: 1; color: $text-muted; }
    KeysUsbPane .toggle { height: 3; margin-top: 1; }
    KeysUsbPane .toggle Label { padding: 1 1; }
    KeysUsbPane #disabled-row { height: 3; margin-top: 1; }
    KeysUsbPane #disabled { padding: 1 1; width: 1fr; }
    KeysUsbPane #rates { layout: horizontal; width: auto; }
    KeysUsbPane #response { max-width: 60; }
    """

    def __init__(self, title: str, *, key_layout: str, id: str | None = None):
        super().__init__(title, id=id)
        self.key_layout = key_layout

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Keys", classes="section")
            with Horizontal(classes="toggle"):
                yield Switch(id="game-mode")
                yield Label("Game Mode [dim](Print Screen lights white)[/]")
            with Horizontal(classes="toggle"):
                yield Switch(id="win-lock")
                yield Label("Win Lock [dim](disables the Windows key)[/]")
            with Horizontal(id="disabled-row"):
                yield Label("Disabled keys: none", id="disabled")
                yield Button("Enable all keys", id="enable-all")
            yield Label("Click keys to disable or re-enable them", classes="field")
            yield KeyboardMap(self.key_layout, id="disable-map")

            yield Label("USB", classes="section")
            yield Label("Report rate (polling)", classes="field")
            with RadioSet(id="rates"):
                for hz in REPORT_RATES_HZ:
                    yield RadioButton(f"{hz} Hz", id=f"rate-{hz}")
            yield Label("Response time (key debounce)", classes="field")
            yield Slider(1, len(RESPONSE_TIMES_MS), id="response",
                         fmt=lambda v: f"{RESPONSE_TIMES_MS[v - 1]} ms")

    # --- keyboard -> UI ---------------------------------------------------

    def show(self, info: Info):
        with self.app.prevent(Switch.Changed, RadioSet.Changed, RadioButton.Changed, Slider.Changed):
            self.query_one("#game-mode", Switch).value = info.game_mode
            self.query_one("#win-lock", Switch).value = info.win_lock
            if info.report_rate:
                self.query_one(f"#rate-{info.report_rate}", RadioButton).value = True
            if info.response_time in RESPONSE_TIMES_MS:
                self.query_one("#response", Slider).value = RESPONSE_TIMES_MS.index(info.response_time) + 1
        self.query_one("#disabled", Label).update(
            f"Disabled keys: {', '.join(info.disabled_keys) or 'none'}")
        self.query_one("#enable-all", Button).disabled = not info.disabled_keys
        km = self.query_one("#disable-map", KeyboardMap)
        km.keymap = self.app.klim.keymap  # cached by info()
        km.selection = info.disabled_indices
        km.dimmed = set(info.disabled_indices)
        km.set_colors({r.k: DISABLED if r.k in km.dimmed else ENABLED for r in km.rects})

    # --- UI -> keyboard ---------------------------------------------------

    def on_keyboard_map_selection_changed(self, event: KeyboardMap.SelectionChanged):
        km = event.keymap
        km.dimmed = set(event.selection)
        km.set_colors({r.k: DISABLED if r.k in km.dimmed else ENABLED for r in km.rects})
        disabled = set(event.selection)
        self.app.debounce("key-mask", lambda: self.app.change(lambda k: k.set_disabled(disabled)))

    def on_switch_changed(self, event: Switch.Changed):
        on = event.value
        if event.switch.id == "game-mode":
            self.app.change(lambda k: k.set_game_mode(on))
        elif event.switch.id == "win-lock":
            self.app.change(lambda k: k.set_win_lock(on))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "enable-all":
            self.app.change(lambda k: k.enable_all_keys())

    def on_radio_set_changed(self, event: RadioSet.Changed):
        hz = REPORT_RATES_HZ[event.index]
        self.app.change(lambda k: k.set_report_rate(hz))

    def on_slider_changed(self, event: Slider.Changed):
        ms = RESPONSE_TIMES_MS[event.value - 1]
        self.app.debounce("response", lambda: self.app.change(lambda k: k.set_response_time(ms)))
