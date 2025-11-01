from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, cast

from textual.widgets import TextArea

from ..chat_view import ChatView

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..app import ChatApp


class ClipboardActionsMixin:
    """Clipboard-related helpers and actions for the chat app."""

    def _copy_text_to_clipboard(self, text: str, success_message: str) -> bool:
        app = cast("ChatApp", self)
        if not text.strip():
            app.bell()
            return False

        try:
            app.copy_to_clipboard(text)
            self._notify_chat(success_message)
            return True
        except Exception as primary_error:
            logger.debug(f"Primary clipboard copy failed: {primary_error}")

        try:
            import pyperclip  # type: ignore

            pyperclip.copy(text)  # type: ignore[attr-defined]
            self._notify_chat(success_message)
            return True
        except Exception as e:
            logger.debug(f"pyperclip fallback failed: {e}")

        return False

    def _notify_chat(self, message: str) -> None:
        app = cast("ChatApp", self)
        if not message:
            return
        try:
            chat = app.query_one("#chat", ChatView)
            chat.append_block(message)
        except Exception:
            pass

    def _copy_textarea(
        self, textarea: TextArea, include_full_text: bool = False
    ) -> bool:
        selected = getattr(textarea, "selected_text", "")
        success_message = (
            "[ok] Tool details copied to clipboard"
            if textarea.id == "tool_details"
            else "[ok] Text copied to clipboard"
        )

        if selected:
            return self._copy_text_to_clipboard(selected, success_message)

        if include_full_text and textarea.text.strip():
            return self._copy_text_to_clipboard(textarea.text, success_message)

        return False

    def action_copy(self) -> None:
        try:
            app = cast("ChatApp", self)
            focused: Optional[object] = app.screen.focused  # type: ignore[attr-defined]
        except Exception:
            focused = None

        if isinstance(focused, TextArea):
            if self._copy_textarea(focused, include_full_text=True):
                return
            logger.debug("TextArea copy did not succeed; falling back")
        else:
            panel = app._get_tool_panel()
            if panel:
                try:
                    details = panel.query_one("#tool_details", TextArea)
                    if self._copy_textarea(
                        details, include_full_text=details.has_focus
                    ):
                        return
                except Exception as e:
                    logger.debug(
                        f"Tool details copy check failed, falling back to chat copy: {e}"
                    )

        try:
            chat = app.query_one("#chat", ChatView)
            selection = chat.text_selection
            if selection:
                selection_text = chat.get_selection(selection)
                if selection_text:
                    text, _ = selection_text
                    if self._copy_text_to_clipboard(
                        text, "[ok] Selection copied to clipboard"
                    ):
                        return
        except Exception as e:
            logger.debug(f"Selection copy fallback failed: {e}")

        self.action_copy_chat()

    def action_copy_chat(self) -> None:
        app = cast("ChatApp", self)
        try:
            chat = app.query_one("#chat", ChatView)
            text = chat.get_text()
            if not text.strip():
                app.bell()
                return
        except Exception as e:
            logger.error(f"Error getting chat text: {e}")
            app.bell()
            return

        if self._copy_text_to_clipboard(text, "[ok] Chat history copied to clipboard"):
            return

        try:
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chat_export_{timestamp}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            chat.append_block(f"[ok] Chat history exported to ./{filename}")
        except Exception as e:
            logger.error(f"Error writing chat export file: {e}")
            app.bell()

    def action_copy_tool_details(self) -> None:
        app = cast("ChatApp", self)
        panel = app._get_tool_panel()
        if not panel:
            app.bell()
            return

        try:
            details = panel.query_one("#tool_details", TextArea)
        except Exception:
            app.bell()
            return

        if self._copy_textarea(details, include_full_text=True):
            return

        app.bell()
