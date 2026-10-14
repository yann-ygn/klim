import queue
import threading
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import Footer, Header, TabbedContent

from ..control import Info, Klim
from ..device import State
from .keys_usb import KeysUsbPane
from .lighting import LightingPane
from .pane import Pane

DEBOUNCE = 0.15  # seconds; sliders only write once they settle


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
            yield KeysUsbPane("Keys & USB", id="keys-usb")
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
        for pane in self.query(Pane):
            pane.show(info)

    def change(self, fn: Callable[[Klim], object]):
        """Send a change to the keyboard, then re-read everything to show what stuck."""
        self.device.submit(fn, lambda _: self.refresh_info())

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
