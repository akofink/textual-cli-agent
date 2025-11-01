from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..app import ChatApp

logger = logging.getLogger(__name__)


class ThemeActionsMixin:
    """Persist theme changes driven by Textual actions."""

    def action_toggle_dark(self) -> None:
        app = cast("ChatApp", self)
        super().action_toggle_dark()  # type: ignore[misc]
        try:
            app.config.set("theme", app.theme)
        except Exception as e:
            logger.error(f"Failed to save theme preference: {e}")

    def action_set_theme(self, theme: str) -> None:
        app = cast("ChatApp", self)
        handled_by_parent = False
        parent = super(ThemeActionsMixin, self)
        parent_action = getattr(parent, "action_set_theme", None)
        if callable(parent_action):
            try:
                parent_action(theme)  # type: ignore[misc]
                handled_by_parent = True
            except Exception:
                handled_by_parent = False

        if not handled_by_parent:
            try:
                app.theme = theme
            except Exception as e:
                logger.error(f"Failed to set theme '{theme}': {e}")
                return

        try:
            app.config.set("theme", app.theme)
        except Exception as e:
            logger.error(f"Failed to save theme preference: {e}")

    def watch_theme(self, theme: str) -> None:  # type: ignore[override]
        try:
            cast("ChatApp", self).config.set("theme", theme)
        except Exception as e:
            logger.error(f"Failed to persist theme in watch_theme: {e}")

    def watch_dark(self, dark: bool) -> None:  # type: ignore[override]
        try:
            app = cast("ChatApp", self)
            app.config.set("theme", app.theme)
        except Exception as e:
            logger.error(f"Failed to persist theme in watch_dark: {e}")
