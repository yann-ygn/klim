"""Small widgets Textual doesn't ship: a slider and a color swatch."""

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.color import Color
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

RAINBOW = ["#ff0000", "#ff8000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"]


class Slider(Widget, can_focus=True):
    """Horizontal integer slider: drag/click with the mouse, or arrow keys."""

    COMPONENT_CLASSES = {"slider--fill", "slider--knob"}
    DEFAULT_CSS = """
    Slider {
        height: 1;
        width: 1fr;
        min-width: 20;
        color: $text-muted;
    }
    Slider:focus {
        color: $text;
    }
    Slider > .slider--fill {
        color: $accent;
    }
    Slider > .slider--knob {
        color: $accent;
        text-style: bold;
    }
    Slider:focus > .slider--knob {
        color: $text;
    }
    """
    BINDINGS = [
        Binding("left", "step(-1)", "Less", show=False),
        Binding("right", "step(1)", "More", show=False),
        Binding("home", "jump(0)", show=False),
        Binding("end", "jump(1)", show=False),
    ]

    value: reactive[int] = reactive(0)

    class Changed(Message):
        def __init__(self, slider: "Slider", value: int):
            super().__init__()
            self.slider = slider
            self.value = value

        @property
        def control(self) -> "Slider":
            return self.slider

    def __init__(self, minimum: int, maximum: int, value: int | None = None, *,
                 fmt=str, id: str | None = None):
        super().__init__(id=id)
        self.minimum, self.maximum, self.fmt = minimum, maximum, fmt
        self._dragging = False
        self.set_reactive(Slider.value, minimum if value is None else value)

    def validate_value(self, value: int) -> int:
        return max(self.minimum, min(self.maximum, value))

    def watch_value(self, value: int):
        self.post_message(self.Changed(self, value))

    def _label(self) -> str:
        return f" {self.fmt(self.value)}".ljust(len(self.fmt(self.maximum)) + 2)

    def _bar_width(self) -> int:
        return max(2, self.size.width - len(self._label()))

    def render(self) -> Text:
        width = self._bar_width()
        span = self.maximum - self.minimum
        knob = round((self.value - self.minimum) / span * (width - 1)) if span else 0
        text = Text()
        text.append("━" * knob, style=self.get_component_rich_style("slider--fill"))
        text.append("●", style=self.get_component_rich_style("slider--knob"))
        text.append("─" * (width - knob - 1))
        text.append(self._label())
        return text

    def _value_at(self, x: int) -> int:
        width = self._bar_width()
        x = max(0, min(width - 1, x))
        return self.minimum + round(x / (width - 1) * (self.maximum - self.minimum))

    def on_mouse_down(self, event: events.MouseDown):
        self._dragging = True
        self.capture_mouse()
        self.focus()
        self.value = self._value_at(event.x)

    def on_mouse_move(self, event: events.MouseMove):
        if self._dragging:
            self.value = self._value_at(event.x)

    def on_mouse_up(self, event: events.MouseUp):
        self._dragging = False
        self.release_mouse()

    def action_step(self, delta: int):
        self.value += delta

    def action_jump(self, end: int):
        self.value = self.maximum if end else self.minimum


class Swatch(Widget, can_focus=True):
    """A clickable color tile; rgb=None draws a rainbow (multicolor)."""

    DEFAULT_CSS = """
    Swatch {
        width: 8;
        height: 4;
        margin-right: 1;
        border: tall $panel;
        content-align: center middle;
    }
    Swatch:focus {
        border: tall $foreground 50%;
    }
    Swatch.-selected {
        border: tall $accent;
    }
    Swatch:disabled {
        opacity: 40%;
    }
    """
    BINDINGS = [Binding("enter,space", "select", "Select", show=False)]

    rgb: reactive[bytes | None] = reactive(None)
    selected: reactive[bool] = reactive(False)

    class Selected(Message):
        def __init__(self, swatch: "Swatch"):
            super().__init__()
            self.swatch = swatch

        @property
        def control(self) -> "Swatch":
            return self.swatch

    def __init__(self, index: int, rgb: bytes | None, *, tooltip: str | None = None,
                 id: str | None = None):
        super().__init__(id=id or f"swatch-{index}")
        self.index = index
        self.set_reactive(Swatch.rgb, rgb)
        if tooltip:
            self.tooltip = tooltip

    def watch_selected(self, selected: bool):
        self.set_class(selected, "-selected")

    def render(self) -> Text:
        width = max(1, self.content_size.width)
        height = max(1, self.content_size.height)
        if self.rgb is None:
            line = Text()
            for i in range(width):
                line.append(" ", style=f"on {RAINBOW[i * len(RAINBOW) // width]}")
        else:
            line = Text(" " * width, style=f"on {Color(*self.rgb).hex}")
        return Text("\n").join([line] * height)

    def on_click(self):
        self.action_select()

    def action_select(self):
        if not self.disabled:
            self.post_message(self.Selected(self))
