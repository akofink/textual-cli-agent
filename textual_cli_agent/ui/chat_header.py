from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Button, Header
from textual.widgets._header import (
    HeaderClock,
    HeaderClockSpace,
    HeaderIcon,
    HeaderTitle,
)


class ChatHeader(Header):
    """Header with an inline quit button."""

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield HeaderIcon().data_bind(Header.icon)
        yield HeaderTitle()
        clock_widget = (
            HeaderClock().data_bind(Header.time_format)
            if self._show_clock
            else HeaderClockSpace()
        )
        yield clock_widget
        yield Button(
            "✕",
            id="header_quit_button",
            tooltip="Quit (Ctrl+Q)",
            classes="quit-button header-button",
        )
