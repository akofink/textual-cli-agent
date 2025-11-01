from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, cast

from ..chat_view import ChatView

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..app import ChatApp


class TodoActionsMixin:
    """Maintain the lightweight todo list displayed alongside chat."""

    _todos: List[str]
    _show_todo: bool

    def _render_todos(self, chat: ChatView) -> None:
        app = cast("ChatApp", self)
        try:
            if not app._show_todo:
                return
            lines = ["[todo]"]
            if not app._todos:
                lines.append("(empty)")
            else:
                for i, item in enumerate(app._todos, start=1):
                    lines.append(f"{i}. {item}")
            chat.append_block("\n".join(lines))

            todo_panel = app._get_todo_panel()
            if todo_panel:
                try:
                    todo_panel.update_todos(app._todos)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error rendering todos: {e}")

    def action_toggle_todo(self) -> None:
        app = cast("ChatApp", self)
        try:
            app._show_todo = not app._show_todo
            app.config.set("show_todo", app._show_todo)
            chat = app.query_one("#chat", ChatView)
            app._render_todos(chat)
        except Exception as e:
            logger.error(f"Error toggling TODO panel: {e}")
