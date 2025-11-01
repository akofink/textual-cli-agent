from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.command import Hit, Hits, Provider as CommandProvider

if TYPE_CHECKING:
    from .app import ChatApp


class ChatCommands(CommandProvider):
    """Command provider for chat application commands."""

    async def search(self, query: str) -> Hits:
        """Search for matching commands."""
        matcher = self.matcher(query)

        commands = [
            (
                "list sessions",
                "List Sessions",
                "action_list_sessions",
                "Show available past sessions",
            ),
            (
                "resume session",
                "Resume Session",
                "action_resume_session",
                "Resume a past session by selecting from a list",
            ),
            (
                "toggle tools",
                "Toggle Tools Panel",
                "action_toggle_tools",
                "Show/hide the tools panel (F2)",
            ),
            (
                "toggle todo panel",
                "Toggle Todo Panel",
                "action_toggle_todo_panel",
                "Show/hide the todo panel (F3)",
            ),
            (
                "toggle todo",
                "Toggle TODO in Chat",
                "action_toggle_todo",
                "Show/hide todos in chat (Ctrl+T)",
            ),
            (
                "copy chat",
                "Copy Chat Content",
                "action_copy_chat",
                "Copy chat content to clipboard (Ctrl+Y)",
            ),
            (
                "clear chat",
                "Clear Chat",
                "action_clear_chat",
                "Clear the chat window (Ctrl+L)",
            ),
            (
                "help",
                "Show Help",
                "action_help_panel",
                "Show help information (Ctrl+?)",
            ),
            (
                "quit",
                "Quit Application",
                "action_quit",
                "Exit the application (Ctrl+C/Q)",
            ),
            (
                "scroll to end",
                "Scroll to End",
                "action_scroll_end",
                "Scroll chat to bottom (End)",
            ),
            (
                "theme toggle",
                "Toggle Theme",
                "action_toggle_dark",
                "Switch between light and dark theme",
            ),
        ]

        app = self.app  # Get reference to app
        assert isinstance(app, ChatApp)  # Type hint for mypy

        for command_text, title, action_name, help_text in commands:
            score = matcher.match(command_text)
            if score > 0:
                action = getattr(app, action_name, None)
                if action and callable(action):
                    yield Hit(
                        score, matcher.highlight(title), partial(action), help=help_text
                    )
