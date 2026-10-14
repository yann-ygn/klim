from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, RadioButton, RadioSet

from ..control import Info, Klim
from ..device import CUSTOM_MODE_BASE, SLOTS
from .keymap import ALL_KEYS, KeyboardMap
from .pane import Pane
from .widgets import Swatch

OFF = b"\0\0\0"


class PerKeyPane(Pane):
    DEFAULT_CSS = """
    PerKeyPane > Vertical { padding: 0 1; height: auto; }
    PerKeyPane .row { height: auto; margin-top: 1; }
    PerKeyPane .row Label { padding: 1 1 0 0; }
    PerKeyPane #slots { layout: horizontal; width: auto; }
    PerKeyPane #paint-hex { width: 14; }
    PerKeyPane #quick Swatch { width: 6; height: 3; margin-right: 0; }
    PerKeyPane Button { margin-left: 1; min-width: 10; }
    PerKeyPane #status { color: $text-muted; padding: 1 0 0 1; }
    """

    def __init__(self, title: str, *, key_layout: str, id: str | None = None):
        super().__init__(title, id=id)
        self.key_layout = key_layout
        self.slot: int | None = None
        self.buf: bytearray | None = None  # slot colors as on the keyboard (LED order)
        self.original: bytes | None = None  # slot as loaded, for Revert
        self.klim: Klim | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="row"):
                yield Label("Slot")
                with RadioSet(id="slots"):
                    for s in range(SLOTS):
                        yield RadioButton(f"DIY{s + 1}", id=f"slot-{s}")
            yield KeyboardMap(self.key_layout, id="map")
            with Horizontal(classes="row", id="quick"):
                yield Label("Color")
                yield Input(placeholder="#rrggbb", id="paint-hex", max_length=7)
                for i in range(7):
                    yield Swatch(i + 1, OFF, id=f"paint-{i + 1}")
                yield Swatch(0, OFF, tooltip="off", id="paint-off")
            with Horizontal(classes="row"):
                yield Button("Select all", id="select-all")
                yield Button("Clear selection", id="select-none")
                yield Button("Revert slot", id="revert", variant="warning")
                yield Label("", id="status")

    @property
    def map(self) -> KeyboardMap:
        return self.query_one("#map", KeyboardMap)

    # --- keyboard -> UI ---------------------------------------------------

    def show(self, info: Info):
        palette = info.palette
        for swatch in self.query("#quick Swatch").results(Swatch):
            if swatch.index:
                swatch.rgb = palette[swatch.index - 1]
                swatch.tooltip = f"#{palette[swatch.index - 1].hex()}"
        if self.slot is None:
            mode = info.state.mode
            self.load_slot(mode - CUSTOM_MODE_BASE if mode >= CUSTOM_MODE_BASE else 0)

    def reload(self):
        """Re-read the current slot from the keyboard (discards Revert history)."""
        if self.slot is not None:
            self.load_slot(self.slot)

    def load_slot(self, slot: int):
        def read(k: Klim):
            return k, k.keymap, k.read_slot(slot)

        def loaded(result):
            self.klim, keymap, buf = result
            self.slot, self.buf, self.original = slot, buf, bytes(buf)
            self.map.keymap = keymap
            with self.app.prevent(RadioSet.Changed, RadioButton.Changed):
                self.query_one(f"#slot-{slot}", RadioButton).value = True
            self.redraw()
        self.app.device.submit(read, loaded)

    def redraw(self):
        self.map.set_colors({k: self.klim.key_color(self.buf, k) for k in ALL_KEYS})
        n = len(self.map.selection)
        changed = self.buf != self.original
        self.query_one("#status", Label).update(
            f"{n} key{'s' if n != 1 else ''} selected" + (" · modified" if changed else ""))
        self.query_one("#revert", Button).disabled = not changed

    # --- UI -> keyboard ---------------------------------------------------

    def paint(self, rgb: bytes):
        if self.buf is None:
            return
        if not self.map.selection:
            self.app.notify("Select keys on the map first (click, drag, or arrows + space)")
            return
        for k in self.map.selection:
            self.klim.paint(self.buf, k, rgb)
        self.redraw()
        self.upload()

    def upload(self):
        slot, data = self.slot, bytes(self.buf)
        self.app.debounce("perkey", lambda: self.app.change(lambda k: k.write_slot(slot, data)))

    def on_keyboard_map_selection_changed(self, event: KeyboardMap.SelectionChanged):
        self.redraw()

    def on_swatch_selected(self, event: Swatch.Selected):
        event.stop()
        self.paint(event.swatch.rgb)

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip().lstrip("#")
        try:
            rgb = bytes.fromhex(text)
            assert len(rgb) == 3
        except (ValueError, AssertionError):
            self.app.notify(f"'{text}' is not a #rrggbb color", severity="error")
            return
        self.paint(rgb)

    def on_radio_set_changed(self, event: RadioSet.Changed):
        self.map.selection = frozenset()
        self.load_slot(event.index)
        self.app.change(lambda k: k.set_lighting(mode=CUSTOM_MODE_BASE + event.index))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "select-all":
            self.map.action_select_all()
        elif event.button.id == "select-none":
            self.map.action_select_none()
        elif event.button.id == "revert" and self.original is not None:
            self.buf = bytearray(self.original)
            self.redraw()
            self.upload()
