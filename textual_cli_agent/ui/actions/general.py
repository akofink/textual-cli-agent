from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from ..chat_view import ChatView

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..app import ChatApp


class GeneralActionsMixin:
    """Common chat window actions."""

    def action_help_panel(self) -> None:
        app = cast("ChatApp", self)
        try:
            chat = app.query_one("#chat", ChatView)
            chat.append_block(
                "[help]\n"
                "Shortcuts:\n"
                "  Ctrl+P  Command palette (search all commands)\n"
                "  Ctrl+D  Toggle theme (via command palette)\n"
                "  F2      Toggle Tools panel\n"
                "  Ctrl+Y  Copy chat\n"
                "  Ctrl+Shift+C Copy tool details\n"
                "  Ctrl+L  Clear chat\n"
                "  Home/End Scroll\n"
                "Commands: type /help for full list"
            )
        except Exception as e:
            logger.error(f"Error showing help panel: {e}")

    def action_clear_chat(self) -> None:
        app = cast("ChatApp", self)
        try:
            chat = app.query_one("#chat", ChatView)
            chat.clear()
            chat._current_text = ""
        except Exception as e:
            logger.error(f"Error clearing chat: {e}")

    def action_scroll_home(self) -> None:
        app = cast("ChatApp", self)
        try:
            chat = app.query_one("#chat", ChatView)
            chat.scroll_home(animate=True)
        except Exception as e:
            logger.error(f"Error scrolling to home: {e}")

    def action_scroll_end(self) -> None:
        app = cast("ChatApp", self)
        try:
            chat = app.query_one("#chat", ChatView)
            chat.scroll_end(animate=True)
        except Exception as e:
            logger.error(f"Error scrolling to end: {e}")
