from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList
from textual.widgets.option_list import Option

from ..control import Info
from .pane import Pane

MARKER = "state_0x88.bin"  # present in every backup


def find_backups(base: Path) -> list[Path]:
    """Backup folders in `base` (and `base` itself if it is one), newest first."""
    if not base.is_dir():
        return []
    found = [d for d in base.iterdir() if (d / MARKER).is_file()]
    if (base / MARKER).is_file():
        found.append(base)
    return sorted(found, key=lambda d: (d / MARKER).stat().st_mtime, reverse=True)


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Grid {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: auto 3;
        padding: 1 2;
        width: 70;
        height: auto;
        border: thick $warning 80%;
        background: $surface;
    }
    ConfirmScreen #question { column-span: 2; width: 1fr; }
    ConfirmScreen Button { width: 100%; }
    """

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label(self.question, id="question")
            yield Button("Restore", variant="error", id="yes")
            yield Button("Cancel", variant="primary", id="no")

    def on_mount(self):
        self.query_one("#no", Button).focus()  # destructive: Enter must not restore

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "yes")


class BackupPane(Pane):
    DEFAULT_CSS = """
    BackupPane > VerticalScroll { padding: 0 2; }
    BackupPane .field { margin-top: 1; color: $text-muted; width: 1fr; }
    BackupPane .row { height: auto; margin-top: 1; }
    BackupPane #backup-dir { width: 1fr; }
    BackupPane #backup-list { height: 12; margin-top: 1; }
    BackupPane Button { margin-right: 1; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Backups folder", classes="field")
            with Horizontal(classes="row"):
                yield Input(str(Path("backup")), id="backup-dir")
                yield Button("Rescan", id="rescan")
            yield OptionList(id="backup-list")
            with Horizontal(classes="row"):
                yield Button("Back up now", variant="primary", id="backup-now")
                yield Button("Restore selected", variant="error", id="restore")
            yield Label("Backups hold the lighting state, palette, all 5 DIY slots, disabled keys, "
                        "Game Mode, USB settings and the keymap (which is never written back).",
                        classes="field")

    def on_mount(self):
        self.rescan()

    def show(self, info: Info):
        pass

    @property
    def base(self) -> Path:
        return Path(self.query_one("#backup-dir", Input).value.strip() or ".")

    def rescan(self):
        backups = find_backups(self.base)
        options = self.query_one("#backup-list", OptionList)
        options.clear_options()
        for d in backups:
            when = datetime.fromtimestamp((d / MARKER).stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            options.add_option(Option(f"{d.name or d}  [dim]{when}[/]", id=str(d)))
        if backups:
            options.highlighted = 0
        self.query_one("#restore", Button).disabled = not backups

    def on_input_submitted(self, event: Input.Submitted):
        self.rescan()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "rescan":
            self.rescan()
        elif event.button.id == "backup-now":
            self.backup()
        elif event.button.id == "restore":
            self.confirm_restore()

    def backup(self):
        path = self.base / datetime.now().strftime("%Y-%m-%d_%H%M%S")

        def done(saved: list[str]):
            self.app.notify(f"Saved {', '.join(saved)} to {path}", title="Backup")
            self.rescan()
        self.app.device.submit(lambda k: k.backup(path), done)

    def confirm_restore(self):
        options = self.query_one("#backup-list", OptionList)
        if options.highlighted is None:
            return
        path = Path(options.get_option_at_index(options.highlighted).id)

        def answered(yes: bool | None):
            if not yes:
                return

            def done(restored: list[str]):
                self.app.notify(f"Restored {', '.join(restored)}", title="Restore")
                self.app.reload_all()
            self.app.device.submit(lambda k: k.restore(path), done)

        self.app.push_screen(ConfirmScreen(
            f"Restore [b]{path}[/b] to the keyboard?\n\nThis overwrites the current lighting, "
            "palette, DIY slots, disabled keys, Game Mode and USB settings."), answered)
