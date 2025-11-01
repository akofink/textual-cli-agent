from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, cast

from ..todo_panel import TodoPanel
from ..tool_panel import ToolPanel

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..app import ChatApp


class PanelActionsMixin:
    """Helpers for showing/hiding auxiliary panels."""

    _tool_panel_widget: Optional[ToolPanel]
    _todo_panel_widget: Optional[TodoPanel]

    def _get_tool_panel(self) -> Optional[ToolPanel]:
        app = cast("ChatApp", self)
        panel = app._tool_panel_widget
        if panel and panel.app:
            return panel
        try:
            panel = app.query_one("#tool_panel", ToolPanel)
            app._tool_panel_widget = panel
            return panel
        except Exception:
            return None

    def _get_todo_panel(self) -> Optional[TodoPanel]:
        app = cast("ChatApp", self)
        panel = app._todo_panel_widget
        if panel and panel.app:
            return panel
        try:
            panel = app.query_one("#todo_panel", TodoPanel)
            app._todo_panel_widget = panel
            return panel
        except Exception:
            return None

    def action_toggle_tools(self) -> None:
        panel = self._get_tool_panel()
        if not panel:
            logger.warning("Tool panel is not available to toggle")
            return
        try:
            panel.toggle_visibility()
        except Exception as e:
            logger.error(f"Error toggling tool panel: {e}")

    def action_toggle_todo_panel(self) -> None:
        app = cast("ChatApp", self)
        panel = self._get_todo_panel()
        if not panel:
            logger.warning("Todo panel is not available to toggle")
            return
        try:
            panel.toggle_visibility()
            if panel.visible:
                panel.update_todos(app._todos)
        except Exception as e:
            logger.error(f"Error toggling todo panel: {e}")
