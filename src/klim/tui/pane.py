from textual.widgets import TabPane

from ..control import Info


class Pane(TabPane):
    """A tab that mirrors part of the keyboard's state."""

    def show(self, info: Info):
        """Update widgets from `info` without sending anything back to the keyboard."""
