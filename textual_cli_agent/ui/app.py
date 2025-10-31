from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import json
import asyncio
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    LoadingIndicator,
    RichLog,
    Static,
    TextArea,
)
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from textual import events
from textual.command import Hit, Hits, Provider as CommandProvider
from functools import partial
from rich.markdown import Markdown
from rich.text import Text
from textual.selection import Selection
from textual.strip import Strip

from ..engine import AgentEngine
from ..providers.base import Provider, ProviderConfig, ProviderFactory
from ..mcp.client import McpManager
from ..config import ConfigManager
from ..session_store import SessionStore
from .todo_panel import TodoPanel
from .tool_panel import ToolPanel

logger = logging.getLogger(__name__)


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
                # Get the action method from the app
                action = getattr(app, action_name, None)
                if action and callable(action):
                    yield Hit(
                        score, matcher.highlight(title), partial(action), help=help_text
                    )


class ChatHeader(Header):
    """Header with an inline quit button."""

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield from super().compose()
        yield Button(
            "✕",
            id="header_quit_button",
            tooltip="Quit (Ctrl+Q)",
            classes="quit-button header-button",
        )


class ChatView(RichLog):  # type: ignore[misc]
    def __init__(self, **kwargs) -> None:
        # Extract widget-specific arguments before passing to RichLog
        super().__init__(
            auto_scroll=True,
            markup=True,
            highlight=False,  # disable code highlighting during streaming to reduce mixing
            max_lines=20000,  # larger buffer
            **kwargs,
        )
        self._current_text = ""

    def get_text(self) -> str:
        """Get all text content for copying."""
        # Extract plain text from all the Rich renderables
        try:
            if getattr(self, "lines", None):
                return "\n".join(strip.text for strip in self.lines)
            internal_lines = getattr(self, "_lines", None)
            if internal_lines is not None:
                collected = []
                for line in internal_lines:
                    if hasattr(line, "plain"):
                        collected.append(line.plain)
                    else:
                        collected.append(str(line))
                if collected:
                    return "\n".join(collected)
        except Exception:
            pass
        return self._current_text

    def append_text(self, text: str) -> None:
        """Append streaming text with sane wrapping."""
        self._current_text += text
        try:
            rich_text = Text(text, no_wrap=False, overflow="fold")
            self.write(rich_text)
        except Exception as e:
            logger.error(f"Error writing text to RichLog: {e}")
            try:
                self.write(text)
            except Exception:
                pass

    def append_block(self, md: str) -> None:
        """Append markdown as a formatted block with clear separation."""
        self._current_text += f"\n{md}\n"
        try:
            markdown = Markdown(md)
            self.write(markdown)
        except Exception as e:
            logger.error(f"Error rendering markdown in RichLog: {e}")
            try:
                self.write(md)
            except Exception:
                pass

    def append_hr(self) -> None:
        try:
            self.write(Markdown("\n---\n"))
        except Exception:
            try:
                self.write("\n---\n")
            except Exception:
                pass

    @property
    def allow_select(self) -> bool:  # type: ignore[override]
        return True

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Provide the currently selected text to Textual's selection system."""
        try:
            lines = [strip.text for strip in self.lines]
        except Exception:
            lines = []
        if not lines:
            return None
        extracted = selection.extract("\n".join(lines))
        if not extracted:
            return None
        return extracted, "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self._line_cache.clear()
        self.refresh()

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        base_line = super()._render_line(y, scroll_x, width)
        line = base_line
        selection = self.text_selection

        if selection is not None:
            span = selection.get_span(y)
            if span is not None and line.cell_length > 0:
                start, end = span
                if end == -1:
                    end = scroll_x + line.cell_length

                highlight_start = max(start - scroll_x, 0)
                highlight_end = min(end - scroll_x, line.cell_length)

                if highlight_end > highlight_start:
                    selection_style = self.screen.get_component_rich_style(
                        "screen--selection"
                    )
                    parts: list[Strip] = []
                    if highlight_start > 0:
                        parts.append(line.crop(0, highlight_start))
                    highlighted = line.crop(highlight_start, highlight_end).apply_style(
                        selection_style
                    )
                    parts.append(highlighted)
                    if highlight_end < line.cell_length:
                        parts.append(line.crop(highlight_end, line.cell_length))
                    line = Strip.join(parts)

        return line.apply_offsets(scroll_x, y)


class ChatApp(App):  # type: ignore[misc]
    # TODO: Tool call logs sometimes appear after tool results in UI; investigate event ordering.
    # TODO: Ensure chat_export*.txt files are always gitignored and never committed.

    provider: Provider
    engine: AgentEngine
    _tool_panel_widget: Optional[ToolPanel]
    _todo_panel_widget: Optional[TodoPanel]

    # Add our custom command provider to the command palette
    COMMANDS = App.COMMANDS | {ChatCommands}

    # Track interactive state for session entries (expanded/collapsed)
    _expanded_entries: set[int] = set()

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    Header Title {
        content-align: left middle;
    }

    #content_area {
        layout: horizontal;
        height: 1fr;
        width: 100%;
    }

    #main_area {
        layout: vertical;
        height: 100%;
        width: 1fr;
        min-width: 40%;
    }

    #chat {
        height: 1fr;
        width: 100%;
        overflow-y: auto;
        overflow-x: hidden;
        border: solid $primary;
        scrollbar-background: $panel;
        scrollbar-color: $accent;
        scrollbar-corner-color: $panel;
        scrollbar-size: 1 1;
        text-wrap: wrap;
    }

    #input {
        dock: bottom;
        width: 100%;
        margin: 1 0;
        border: solid $accent;
        background: $surface;
    }

    RichLog {
        background: $surface;
        color: $text;
        border: none;
        padding: 1;
    }

    Input {
        background: $surface;
        color: $text;
        width: 100%;
    }

    #status_container {
        dock: bottom;
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
        width: 100%;
        layout: horizontal;
        align: center middle;
    }

    #status_text {
        text-align: center;
        width: 1fr;
        color: $text;
        margin-right: 1;
    }

    #llm_indicator {
        color: $text;
    }

    .hidden {
        display: none;
    }

    .quit-button {
        background: transparent;
        color: $text;
        border: none;
        padding: 0 1;
        min-width: 3;
        content-align: center middle;
    }

    .quit-button:hover {
        background: $accent;
        color: $text;
    }

    Header .header-button {
        dock: right;
        height: 100%;
        margin: 0 1 0 0;
    }

    #status_container .status-button {
        dock: right;
        margin-left: 1;
        height: 1;
    }

    #tool_panel {
        display: none;
        width: 30%;
        height: 100%;
        border: solid $primary;
        background: $surface;
        min-width: 20%;
        max-width: 45%;
    }

    #tool_panel.visible {
        display: block;
        width: 30%;
    }

    .panel-header {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-align: center;
        content-align: center middle;
        width: 100%;
    }

    .tool-panel-content {
        height: 100%;
        width: 100%;
    }

    .tool-details {
        dock: bottom;
        height: 50%;
        width: 100%;
        border: solid $accent;
        background: $panel;
        padding: 1;
        overflow-y: auto;
        scrollbar-background: $panel;
        scrollbar-color: $accent;
        scrollbar-corner-color: $panel;
        scrollbar-size: 1 1;
    }

    /* Todo panel styles */
    #todo_panel {
        display: none;
        width: 25%;
        min-width: 20%;
        max-width: 40%;
        height: 100%;
        border: solid $primary;
        background: $surface;
    }

    #todo_panel.visible {
        display: block;
        width: 25%;
    }

    .todo-panel-content {
        height: 100%;
        width: 100%;
    }

    .todo-details {
        dock: bottom;
        height: 50%;
        width: 100%;
        border: solid $accent;
        background: $panel;
        padding: 1;
        overflow-y: auto;
    }

    #tool_tree {
        height: 1fr;
        width: 100%;
        background: $surface;
    }

    #todo_tree {
        height: 1fr;
        width: 100%;
        background: $surface;
    }
    """

    BINDINGS = [
        # Keep essential shortcuts that users expect
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+c", "copy", "Copy", show=True),
        Binding("ctrl+shift+c", "copy_tool_details", "Copy Tool", show=True),
        # Removed Ctrl+D binding to avoid accidental quits and repurpose for theme toggle via palette
        # Binding("ctrl+d", "toggle_dark", "Theme", show=True),
        # Keep most common actions as shortcuts
        Binding("f2", "toggle_tools", "Tools", show=True),
        Binding("f3", "toggle_todo_panel", "Todos", show=True),
        Binding("ctrl+y", "copy_chat", "Copy", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        # Navigation shortcuts
        Binding("home", "scroll_home", "Top", show=False),
        Binding("end", "scroll_end", "Bottom", show=False),
        # All other commands available via Ctrl+P command palette
    ]

    def _apply_provider_config(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        system: Optional[str] = None,
    ) -> None:
        try:
            cfg = ProviderConfig(
                model=model or self.provider.cfg.model,
                api_key=self.provider.cfg.api_key,
                base_url=self.provider.cfg.base_url,
                temperature=temperature
                if temperature is not None
                else self.provider.cfg.temperature,
                system_prompt=system
                if system is not None
                else self.provider.cfg.system_prompt,
            )
            # Recreate provider with new config, preserve class type
            prov_name = type(self.provider).__name__.replace("Provider", "").lower()
            # Try to infer factory
            if prov_name in ("openai", "anthropic", "ollama"):
                new_provider = ProviderFactory.create(prov_name, cfg)
            else:
                # Fallback to same class constructor
                new_provider = type(self.provider)(cfg)
            self.provider = new_provider
            self.engine.provider = new_provider
        except Exception as e:
            logger.error(f"Error applying provider config: {e}")

    def _apply_saved_provider_config(self) -> None:
        """Apply any saved provider configuration from config file."""
        try:
            saved_provider = self.config.get("provider")
            saved_model = self.config.get("model")
            saved_temp = self.config.get("temperature")

            # Only apply changes if we have saved values
            changes_needed = False

            # Check if provider type needs to change
            current_provider_type = (
                type(self.provider).__name__.replace("Provider", "").lower()
            )
            if saved_provider and saved_provider != current_provider_type:
                changes_needed = True

            # Check if model or temperature need to change
            if saved_model and saved_model != self.provider.cfg.model:
                changes_needed = True
            if saved_temp is not None and saved_temp != self.provider.cfg.temperature:
                changes_needed = True

            if changes_needed:
                # Create new provider config with saved values
                cfg = ProviderConfig(
                    model=saved_model or self.provider.cfg.model,
                    api_key=self.provider.cfg.api_key,
                    base_url=self.provider.cfg.base_url,
                    temperature=saved_temp
                    if saved_temp is not None
                    else self.provider.cfg.temperature,
                    system_prompt=self.provider.cfg.system_prompt,
                )

                if saved_provider and saved_provider in (
                    "openai",
                    "anthropic",
                    "ollama",
                ):
                    new_provider = ProviderFactory.create(saved_provider, cfg)
                else:
                    # Just update config of existing provider
                    new_provider = type(self.provider)(cfg)

                self.provider = new_provider
                self.engine.provider = new_provider
                logger.debug(
                    f"Applied saved provider config: {saved_provider}, {saved_model}, {saved_temp}"
                )
        except Exception as e:
            logger.warning(f"Failed to apply saved provider config: {e}")

    def _get_tool_panel(self) -> Optional[ToolPanel]:
        panel = self._tool_panel_widget
        if panel and panel.app:
            return panel
        try:
            panel = self.query_one("#tool_panel", ToolPanel)
            self._tool_panel_widget = panel
            return panel
        except Exception:
            return None

    def _get_todo_panel(self) -> Optional[TodoPanel]:
        panel = self._todo_panel_widget
        if panel and panel.app:
            return panel
        try:
            panel = self.query_one("#todo_panel", TodoPanel)
            self._todo_panel_widget = panel
            return panel
        except Exception:
            return None

    def _parse_tool_payload(self, payload: Any) -> Any:
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception:
                return payload
        return payload

    def _apply_tool_result(self, tool_id: str, content: Any) -> None:
        if not tool_id:
            return
        if tool_id in self._tool_calls_by_id:
            self._tool_calls_by_id[tool_id]["result"] = content
        panel = self._get_tool_panel()
        if not panel:
            return
        error_text: Optional[str] = None
        if isinstance(content, dict) and "error" in content:
            error_text = str(content.get("error"))
        try:
            if error_text:
                panel.update_tool_result(tool_id, error=error_text)
            else:
                panel.update_tool_result(tool_id, result=content)
        except Exception as e:
            logger.debug(f"Failed to update tool panel result for {tool_id}: {e}")

    def _record_tool_call(self, tool_id: str, name: str, raw_args: Any) -> None:
        if not tool_id:
            return
        parsed_args = self._parse_tool_payload(raw_args)
        self._tool_calls_by_id[tool_id] = {"name": name, "arguments": parsed_args}
        panel = self._get_tool_panel()
        if panel:
            call_args = (
                parsed_args if isinstance(parsed_args, dict) else {"value": parsed_args}
            )
            try:
                panel.add_tool_call(tool_id, name, call_args)
            except Exception as e:
                logger.debug(f"Failed to add tool call {tool_id} to panel: {e}")
        if tool_id in self._pending_tool_results:
            content = self._pending_tool_results.pop(tool_id)
            self._apply_tool_result(tool_id, content)

    def _record_tool_result(self, tool_id: str, raw_content: Any) -> None:
        if not tool_id:
            return
        parsed_content = self._parse_tool_payload(raw_content)
        self._pending_tool_results[tool_id] = parsed_content
        if tool_id in self._tool_calls_by_id:
            content = self._pending_tool_results.pop(tool_id, parsed_content)
            self._apply_tool_result(tool_id, content)

    def on_key(self, event: events.Key) -> None:
        # Ensure Ctrl+Q always quits, even if widgets handle it differently
        if event.key == "ctrl+q":
            event.prevent_default()
            event.stop()
            self.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in {"quit_button", "header_quit_button"}:
            event.stop()
            self.exit()

    def __init__(
        self,
        provider: Provider,
        mcp_manager: Optional[McpManager] = None,
        initial_messages: Optional[List[Dict[str, Any]]] = None,
        initial_markdown: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.engine = AgentEngine(provider, mcp_manager)
        self.messages: List[Dict[str, Any]] = list(initial_messages or [])
        self._initial_markdown = initial_markdown or ""
        # Track tool calls by id to enhance result display
        self._tool_calls_by_id: Dict[str, Dict[str, Any]] = {}

        # Config persistence
        self.config = ConfigManager()

        # Session store (under XDG config sessions/), deprecates local .textual-debug
        self._session_store = SessionStore(self.config)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_path = self._session_store.start_session(self._session_id)

        # Runtime toggles - load from config with defaults
        self.auto_continue: bool = self.config.get("auto_continue", True)
        self.max_rounds: int = self.config.get("max_rounds", 15)
        # Background processing and queuing
        self._worker_task: Optional[asyncio.Task] = None
        self._pending_count: int = 0
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        # Tool call/result ordering tracking
        self._pending_tool_results: Dict[str, Any] = {}
        self._tool_turn_counter: int = 0
        self._tool_panel_widget: Optional[ToolPanel] = None
        self._todo_panel_widget: Optional[TodoPanel] = None
        # Simple TODO list pane
        self._todos: List[str] = []
        self._show_todo: bool = self.config.get("show_todo", False)

        # Apply any saved provider config overrides
        self._apply_saved_provider_config()

        # Apply saved theme (rely on Textual to validate/resolve)
        saved_theme = self.config.get("theme")
        if saved_theme:
            try:
                self.theme = saved_theme
            except Exception as e:
                logger.warning(f"Failed to apply saved theme '{saved_theme}': {e}")

    def _write_tool_debug(
        self, tool_id: str, event_type: str, data: Dict[str, Any]
    ) -> None:
        """Append tool event to session store for persistent context."""
        try:
            entry = {
                "tool_id": tool_id,
                "event_type": event_type,
                "data": data,
            }
            self._session_store.add_event(entry)
        except Exception as e:
            logger.warning(f"Failed to write tool debug info: {e}")

    def _get_result_summary(self, content: Any) -> str:
        """Get a brief summary of tool result content."""
        if isinstance(content, str):
            if len(content) > 100:
                return f"{content[:97]}..."
            return content or "(empty)"
        elif isinstance(content, dict):
            if "error" in content:
                return f"Error: {content.get('error', 'Unknown')}"
            elif "success" in content:
                return "Success"
            else:
                return f"Dict with {len(content)} keys"
        elif isinstance(content, list):
            return f"List with {len(content)} items"
        else:
            return str(content)[:100]

    def action_toggle_dark(self) -> None:
        """Toggle dark/light theme and save the resolved theme name to config.
        Note: Users may set non-binary themes (e.g., 'solarized-light'); we persist whatever Textual resolves.
        """
        super().action_toggle_dark()
        # Persist the resolved theme name
        try:
            self.config.set("theme", self.theme)
        except Exception as e:
            logger.error(f"Failed to save theme preference: {e}")

    def action_set_theme(self, theme: str) -> None:
        """Set a specific theme by name and persist to config.
        This is called by Textual's command palette when choosing a theme.
        """
        handled_by_parent = False
        parent = super(ChatApp, self)
        parent_action = getattr(parent, "action_set_theme", None)
        if callable(parent_action):
            try:
                parent_action(theme)  # type: ignore[misc]
                handled_by_parent = True
            except Exception:
                handled_by_parent = False

        if not handled_by_parent:
            try:
                self.theme = theme
            except Exception as e:
                logger.error(f"Failed to set theme '{theme}': {e}")
                return
        # Persist resolved theme name
        try:
            self.config.set("theme", self.theme)
        except Exception as e:
            logger.error(f"Failed to save theme preference: {e}")

    # Persist theme changes regardless of how they occur (toggle, palette, programmatic)
    def watch_theme(self, theme: str) -> None:  # type: ignore[override]
        try:
            self.config.set("theme", theme)
        except Exception as e:
            logger.error(f"Failed to persist theme in watch_theme: {e}")

    def watch_dark(self, dark: bool) -> None:  # type: ignore[override]
        # Save the resolved theme name when dark mode toggles
        try:
            self.config.set("theme", self.theme)
        except Exception as e:
            logger.error(f"Failed to persist theme in watch_dark: {e}")

    def _copy_text_to_clipboard(self, text: str, success_message: str) -> bool:
        """Attempt to copy text to clipboard and surface feedback."""
        if not text.strip():
            self.bell()
            return False

        try:
            self.copy_to_clipboard(text)
            try:
                chat = self.query_one("#chat", ChatView)
                if success_message:
                    chat.append_block(success_message)
            except Exception:
                pass
            return True
        except Exception as primary_error:
            logger.debug(f"Primary clipboard copy failed: {primary_error}")

        try:
            import pyperclip  # type: ignore

            pyperclip.copy(text)  # type: ignore[attr-defined]
            try:
                chat = self.query_one("#chat", ChatView)
                if success_message:
                    chat.append_block(success_message)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.debug(f"pyperclip fallback failed: {e}")

        return False

    def _copy_textarea(
        self, textarea: TextArea, include_full_text: bool = False
    ) -> bool:
        """Copy selection (or full text) from a TextArea if available."""
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
        """Context-aware copy shortcut."""
        try:
            focused = self.screen.focused  # type: ignore[attr-defined]
        except Exception:
            focused = None

        if isinstance(focused, TextArea):
            if self._copy_textarea(focused, include_full_text=True):
                return
            logger.debug("TextArea copy did not succeed; falling back")
        else:
            panel = self._get_tool_panel()
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
            chat = self.query_one("#chat", ChatView)
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
        """Enhanced copy functionality inspired by Toad's text interaction."""
        try:
            chat = self.query_one("#chat", ChatView)
            text = chat.get_text()

            # Show visual feedback like Toad
            if not text.strip():
                self.bell()  # Audio feedback for empty content
                return

        except Exception as e:
            logger.error(f"Error getting chat text: {e}")
            self.bell()  # Audio feedback for error
            return

        if self._copy_text_to_clipboard(text, "[ok] Chat history copied to clipboard"):
            return

        # Enhanced fallback: write to a file with better naming
        try:
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chat_export_{timestamp}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            chat.append_block(f"[ok] Chat history exported to ./{filename}")
        except Exception as e:
            logger.error(f"Error writing chat export file: {e}")
            self.bell()  # Audio feedback for error

    def action_copy_tool_details(self) -> None:
        """Copy the current tool details pane to the clipboard."""
        panel = self._get_tool_panel()
        if not panel:
            self.bell()
            return

        try:
            details = panel.query_one("#tool_details", TextArea)
        except Exception:
            self.bell()
            return

        if self._copy_textarea(details, include_full_text=True):
            return

        self.bell()

    def action_help_panel(self) -> None:
        try:
            chat = self.query_one("#chat", ChatView)
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

    def action_toggle_todo(self) -> None:
        try:
            self._show_todo = not self._show_todo
            self.config.set("show_todo", self._show_todo)
            chat = self.query_one("#chat", ChatView)
            self._render_todos(chat)
        except Exception as e:
            logger.error(f"Error toggling TODO panel: {e}")

    def action_clear_chat(self) -> None:
        """Clear chat history - Toad-inspired quick action."""
        try:
            chat = self.query_one("#chat", ChatView)
            chat.clear()
            chat._current_text = ""
        except Exception as e:
            logger.error(f"Error clearing chat: {e}")

    def action_scroll_home(self) -> None:
        """Scroll to top of chat - enhanced navigation."""
        try:
            chat = self.query_one("#chat", ChatView)
            chat.scroll_home(animate=True)
        except Exception as e:
            logger.error(f"Error scrolling to home: {e}")

    def action_scroll_end(self) -> None:
        """Scroll to bottom of chat - enhanced navigation."""
        try:
            chat = self.query_one("#chat", ChatView)
            chat.scroll_end(animate=True)
        except Exception as e:
            logger.error(f"Error scrolling to end: {e}")

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
        """Toggle the todo panel visibility."""
        panel = self._get_todo_panel()
        if not panel:
            logger.warning("Todo panel is not available to toggle")
            return
        try:
            panel.toggle_visibility()
            if panel.visible:
                panel.update_todos(self._todos)
        except Exception as e:
            logger.error(f"Error toggling todo panel: {e}")

    def _status_title(self) -> str:
        return (
            f"ChatApp - provider={type(self.provider).__name__.replace('Provider', '').lower()} "
            f"model={self.provider.cfg.model} temp={self.provider.cfg.temperature} "
            f"auto={self.auto_continue} rounds={self.max_rounds} pending={self._pending_count}"
        )

    def _refresh_header(self) -> None:
        try:
            self.sub_title = self._status_title()
        except Exception:
            pass

    def _set_loading_indicator(self, busy: bool) -> None:
        """Show or hide the loading indicator."""
        try:
            indicator = self.query_one("#llm_indicator", LoadingIndicator)
        except Exception:
            return
        if busy:
            indicator.remove_class("hidden")
            try:
                indicator.loading = True
                indicator.display = True
            except Exception:
                pass
        else:
            indicator.add_class("hidden")
            try:
                indicator.loading = False
                indicator.display = False
            except Exception:
                pass

    def _update_status(self, working: bool = False) -> None:
        """Update the footer status bar with current state."""
        busy = working or self._pending_count > 0
        try:
            status_bar = self.query_one("#status_text", Static)
            if working:
                status_text = f"Working… (pending: {self._pending_count})"
            else:
                status_text = (
                    f"Idle (pending: {self._pending_count})"
                    if self._pending_count > 0
                    else "Idle"
                )
            status_bar.update(status_text)
        except Exception:
            pass  # Status bar may not be mounted yet
        self._set_loading_indicator(busy)

    def _render_todos(self, chat: "ChatView") -> None:
        try:
            if not self._show_todo:
                return
            lines = ["[todo]"]
            if not self._todos:
                lines.append("(empty)")
            else:
                for i, item in enumerate(self._todos, start=1):
                    lines.append(f"{i}. {item}")
            chat.append_block("\n".join(lines))

            # Also update the todo panel if it exists
            todo_panel = self._get_todo_panel()
            if todo_panel:
                try:
                    todo_panel.update_todos(self._todos)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error rendering todos: {e}")

    def action_list_sessions(self) -> None:
        sessions = self._session_store.list_sessions()
        if not sessions:
            try:
                chat = self.query_one("#chat", ChatView)
                chat.append_block("[ok] No sessions found.")
            except Exception:
                pass
            return
        lines = ["[sessions]"]
        for idx, s in enumerate(sessions):
            lines.append(f"{idx + 1}. {s.id}  ({s.created:%Y-%m-%d %H:%M:%S})")
        try:
            chat = self.query_one("#chat", ChatView)
            chat.append_block("\n".join(lines))
        except Exception:
            pass

    def action_resume_session(self) -> None:
        # For now, resume the most recent session; later, add selection UI
        sessions = self._session_store.list_sessions()
        if not sessions:
            try:
                chat = self.query_one("#chat", ChatView)
                chat.append_block("[error] No sessions to resume.")
            except Exception:
                pass
            return
        latest = sorted(sessions, key=lambda s: s.created)[-1]
        self._session_store.resume_session(latest.id)
        # Reconstruct messages and display context
        msgs = self._session_store.reconstruct_messages(latest.id)
        self.messages = msgs
        try:
            chat = self.query_one("#chat", ChatView)
            chat.clear()
            chat._current_text = ""
            chat.append_block(f"[ok] Resumed session {latest.id}")
            # Render messages quickly
            for m in msgs:
                role = m.get("role")
                content = m.get("content", "")
                if role == "user":
                    chat.append_block(f"**You:**\n{content}")
                else:
                    chat.append_block(content)
                chat.append_hr()
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        tool_panel = ToolPanel()
        todo_panel = TodoPanel()
        self._tool_panel_widget = tool_panel
        self._todo_panel_widget = todo_panel
        yield ChatHeader(show_clock=True, id="hdr")
        yield Horizontal(
            Vertical(
                ChatView(id="chat"),
                Input(
                    placeholder="Type a message and press Enter (/help for commands)",
                    id="input",
                    password=False,
                ),
                id="main_area",
            ),
            tool_panel,
            todo_panel,
            id="content_area",
        )
        yield Horizontal(
            LoadingIndicator(id="llm_indicator", classes="hidden"),
            Static("Idle", id="status_text"),
            Button(
                "✕",
                id="quit_button",
                tooltip="Quit (Ctrl+Q)",
                classes="quit-button status-button",
            ),
            id="status_container",
        )
        yield Footer(id="footer")

    async def _worker(self) -> None:
        chat = self.query_one("#chat", ChatView)
        while True:
            prompt = await self._queue.get()
            try:
                # Show user prompt as its own block
                chat.append_block(f"**You:**\n{prompt}")
                chat.append_hr()
                self.messages.append({"role": "user", "content": prompt})
                # Persist user prompt in session
                try:
                    self._session_store.add_event({
                        "event_type": "user_prompt",
                        "content": prompt,
                    })
                except Exception:
                    pass
                await self._run_auto_rounds(chat)
            except Exception as e:
                logger.error(f"Worker error: {e}")
                chat.append_block(f"**[ERROR]** Worker error: {str(e)}")
            finally:
                self._pending_count = max(0, self._pending_count - 1)
                # Update header subtitle with pending
                try:
                    title = f"ChatApp - provider={type(self.provider).__name__.replace('Provider', '').lower()} model={self.provider.cfg.model} temp={self.provider.cfg.temperature} auto={self.auto_continue} rounds={self.max_rounds} pending={self._pending_count}"
                    self.sub_title = title
                except Exception:
                    pass
                self._update_status(working=False)

    def on_mount(self) -> None:
        # Update header title with live status
        try:
            self._refresh_header()
        except Exception:
            pass
        # Initialize footer status
        self._update_status(working=False)
        # Focus the input field on startup
        try:
            self.query_one("#input", Input).focus()
        except Exception:
            pass  # Input may not be mounted yet
        if self._initial_markdown:
            try:
                chat = self.query_one("#chat", ChatView)
                chat.append_block(self._initial_markdown)
            except Exception as e:
                logger.error(f"Error displaying initial markdown: {e}")
        # Start worker for queued prompts if an event loop is running
        try:
            loop = asyncio.get_running_loop()
            if self._worker_task is None:
                self._worker_task = loop.create_task(self._worker())
        except RuntimeError:
            # No running loop (e.g., during some tests); worker will be started later
            pass
        except Exception as e:
            logger.error(f"Failed to start worker: {e}")

    async def _run_auto_rounds(self, chat: "ChatView") -> None:
        rounds = 0
        while True:
            if not self.auto_continue and rounds > 0:
                break
            had_tools_this_round = False
            text_buf = ""

            self._tool_turn_counter += 1
            current_turn_id = self._tool_turn_counter
            panel = self._get_tool_panel()
            if panel:
                try:
                    panel.start_turn(current_turn_id)
                except Exception as e:
                    logger.debug(
                        f"Failed to start tool panel turn {current_turn_id}: {e}"
                    )

            # Show working indicator
            try:
                self.sub_title = "Working..."
            except Exception:
                pass
            self._update_status(working=True)
            async for chunk in self.engine.run_stream(self.messages):
                # Ensure UI stays responsive in long streams (no-op in tests)
                await asyncio.sleep(0)
                try:
                    ctype = chunk.get("type")
                    if ctype == "text":
                        delta = chunk.get("delta", "")
                        if delta:
                            # Surface errors immediately for visibility & tests
                            if "[ERROR]" in delta:
                                chat.append_text(delta)
                            else:
                                # Buffer non-error text to avoid fragmentation
                                text_buf += delta
                                try:
                                    self._session_store.add_event({
                                        "event_type": "assistant_text",
                                        "content": delta,
                                    })
                                except Exception:
                                    pass
                    elif ctype == "tool_call":
                        tool_name = chunk.get("name", "unknown_tool")
                        parsed_args = self._parse_tool_payload(
                            chunk.get("arguments", {})
                        )
                        tool_id = chunk.get("id", "")
                        if tool_id:
                            already_recorded = tool_id in self._tool_calls_by_id
                            self._record_tool_call(tool_id, tool_name, parsed_args)
                            if not already_recorded:
                                self._write_tool_debug(
                                    tool_id,
                                    "call",
                                    {"name": tool_name, "arguments": parsed_args},
                                )

                        # Inline indicator for tool call
                        try:
                            call_args_preview = json.dumps(parsed_args)[:120]
                        except Exception:
                            call_args_preview = str(parsed_args)[:120]
                        chat.append_block(
                            f"[tool call] {tool_name} args: {call_args_preview}"
                        )
                    elif ctype == "tool_result":
                        content = chunk.get("content", "")
                        tool_id = chunk.get("id", "")
                        # Already persisted above

                        parsed_content = self._parse_tool_payload(content)

                        # Write detailed result to debug file
                        if tool_id:
                            self._write_tool_debug(
                                tool_id, "result", {"content": content}
                            )
                            self._record_tool_result(tool_id, parsed_content)

                        # Display simple result indicator in chat
                        result_summary = self._get_result_summary(parsed_content)
                        chat.write(f"✅ Result: {result_summary}")
                        chat.write("\n")
                        try:
                            self._session_store.add_event({
                                "event_type": "tool_result",
                                "id": tool_id,
                                "content": content,
                            })
                        except Exception:
                            pass

                    elif ctype == "append_message":
                        message = chunk.get("message", {})
                        if message:
                            if message.get("role") == "assistant" and message.get(
                                "tool_calls"
                            ):
                                calls = message.get("tool_calls") or []
                                pretty_calls = []
                                for call in calls:
                                    function_data = call.get("function") or {}
                                    call_id = call.get("id", "")
                                    call_name = function_data.get(
                                        "name", "unknown_tool"
                                    )
                                    raw_arguments = function_data.get("arguments")
                                    parsed_arguments = self._parse_tool_payload(
                                        raw_arguments
                                    )
                                    pretty_calls.append({
                                        "id": call_id,
                                        "name": call_name,
                                        "arguments": parsed_arguments,
                                    })
                                    if call_id:
                                        already_recorded = (
                                            call_id in self._tool_calls_by_id
                                        )
                                        self._record_tool_call(
                                            call_id, call_name, parsed_arguments
                                        )
                                        if not already_recorded:
                                            self._write_tool_debug(
                                                call_id,
                                                "call",
                                                {
                                                    "name": call_name,
                                                    "arguments": parsed_arguments,
                                                },
                                            )
                                chat.append_block(
                                    f"[assistant tool_calls]\n{pretty_calls}"
                                )
                            self.messages.append(message)
                    elif ctype == "round_complete":
                        # Flush any buffered text once at end of turn
                        if text_buf:
                            chat.append_block(text_buf)
                            text_buf = ""
                        chat.append_hr()
                        had_tools_this_round = bool(chunk.get("had_tool_calls", False))
                        break
                except Exception as e:
                    logger.error(f"Error processing chunk {chunk}: {e}")
                    chat.append_text(f"[ERROR] Processing error: {str(e)}")
                    continue
            rounds += 1
            # Allow one more round for final response even if we hit max rounds
            if not had_tools_this_round:
                break
            if rounds >= self.max_rounds:
                # Add a message to inform the agent it's at the round limit
                self.messages.append({
                    "role": "user",
                    "content": f"[SYSTEM] You have reached the maximum number of tool-calling rounds ({self.max_rounds}). Please provide a final response without using any more tools.",
                })
                # Allow one final round for response without tools
                text_buf = ""
                try:
                    self.sub_title = "Final response..."
                except Exception:
                    pass
                self._update_status(working=True)
                async for chunk in self.engine.run_stream(self.messages):
                    await asyncio.sleep(0)
                    try:
                        ctype = chunk.get("type")
                        if ctype == "text":
                            delta = chunk.get("delta", "")
                            text_buf += delta
                            chat.append_text(delta)
                        elif ctype == "round_complete":
                            if text_buf:
                                chat.append_block(text_buf)
                            break
                    except Exception as e:
                        logger.error(
                            f"Error processing final response chunk {chunk}: {e}"
                        )
                        continue
                break
            # Restore header subtitle to status between rounds
            try:
                title = f"ChatApp - provider={type(self.provider).__name__.replace('Provider', '').lower()} model={self.provider.cfg.model} temp={self.provider.cfg.temperature} auto={self.auto_continue} rounds={self.max_rounds}"
                self.sub_title = title
            except Exception:
                pass

    def _handle_command(self, line: str, chat: "ChatView") -> bool:
        try:
            parts = line.strip().split()
            if not parts:
                return True
            cmd = parts[0].lower()
            args = parts[1:]

            def ok(msg: str) -> None:
                chat.append_block(f"[ok] {msg}")

            def err(msg: str) -> None:
                chat.append_block(f"[error] {msg}")

            if cmd == "/help":
                ok(
                    "Commands:\n"
                    "/help\n"
                    "/config\n"
                    "/model <name>\n"
                    "/provider <openai|anthropic|ollama>\n"
                    "/temp <float>\n"
                    "/system <text>\n"
                    "/auto <on|off>\n"
                    "/rounds <n>\n"
                    "/parallel <on|off>\n"
                    "/parallel limit <n>\n"
                    "/timeout <seconds>\n"
                    "/tools\n"
                    "/tools enable <name>\n"
                    "/tools disable <name>\n"
                    "/todo add <item>\n"
                    "/todo remove <n>\n"
                    "/todo show|hide\n"
                    "/prune [n]\n"
                )
                return True
            if cmd == "/config":
                config_data = self.config.get_all()
                if config_data:
                    config_lines = [
                        f"  {k}: {v}" for k, v in sorted(config_data.items())
                    ]
                    config_text = "Current configuration:\n" + "\n".join(config_lines)
                    config_text += f"\n\nConfig file: {self.config.config_file_path}"
                else:
                    config_text = "No configuration saved yet.\n\nSettings will be saved when you change them via commands like /model, /temp, etc."
                ok(config_text)
                return True
            if cmd == "/model" and args:
                model_name = " ".join(args)
                self._apply_provider_config(model=model_name)
                self.config.set("model", model_name)
                self._refresh_header()
                ok(f"model set -> {model_name}")
                return True
            if cmd == "/provider" and args:
                prov = args[0].lower()
                if prov not in ("openai", "anthropic", "ollama"):
                    err("provider must be 'openai', 'anthropic', or 'ollama'")
                    return True
                try:
                    cfg = ProviderConfig(
                        model=self.provider.cfg.model,
                        api_key=self.provider.cfg.api_key,
                        base_url=self.provider.cfg.base_url,
                        temperature=self.provider.cfg.temperature,
                        system_prompt=self.provider.cfg.system_prompt,
                    )
                    new_provider = ProviderFactory.create(prov, cfg)
                    self.provider = new_provider
                    self.engine.provider = new_provider
                    self.config.set("provider", prov)
                    self._refresh_header()
                    ok(f"provider -> {prov}")
                except Exception as e:
                    err(f"failed to switch provider: {str(e)}")
                return True
            if cmd == "/temp" and args:
                try:
                    t = float(args[0])
                except Exception:
                    err("temp must be a float")
                    return True
                self._apply_provider_config(temperature=t)
                self.config.set("temperature", t)
                self._refresh_header()
                ok(f"temperature set -> {t}")
                return True
            if cmd == "/system" and args:
                text = " ".join(args)
                self._apply_provider_config(system=text)
                self._refresh_header()
                ok("system prompt updated")
                return True
            if cmd == "/auto" and args:
                val = args[0].lower()
                self.auto_continue = val in ("on", "true", "1", "yes")
                self.config.set("auto_continue", self.auto_continue)
                self._refresh_header()
                ok(f"auto-continue -> {self.auto_continue}")
                return True
            if cmd == "/rounds" and args:
                try:
                    n = int(args[0])
                except Exception:
                    err("rounds must be an integer")
                    return True
                self.max_rounds = max(1, n)
                self.config.set("max_rounds", self.max_rounds)
                self._refresh_header()
                ok(f"max rounds -> {self.max_rounds}")
                return True
            if cmd == "/parallel" and args:
                if args[0] == "limit" and len(args) > 1:
                    try:
                        n = int(args[1])
                    except Exception:
                        err("parallel limit must be an integer")
                        return True
                    self.engine.concurrency_limit = max(1, n)
                    self._refresh_header()
                    ok(f"concurrency limit -> {self.engine.concurrency_limit}")
                    return True
                else:
                    val = args[0].lower()
                    if val in ("on", "off"):
                        # 'on' removes limit; 'off' sets to 1
                        self.engine.concurrency_limit = None if val == "on" else 1
                        self._refresh_header()
                        ok(f"parallel -> {val}")
                        return True
            if cmd == "/timeout" and args:
                try:
                    secs = float(args[0])
                except Exception:
                    err("timeout must be a number (seconds)")
                    return True
                self.engine.tool_timeout = max(1.0, secs)
                self._refresh_header()
                ok(f"tool timeout -> {self.engine.tool_timeout}s")
                return True
            if cmd == "/tools":
                names = [
                    t.get("name", "")
                    for t in self.engine._combined_tool_specs()
                    if t.get("name") is not None
                ]
                if self.engine.enabled_tools is None:
                    enabled = set(names)
                else:
                    enabled = set(self.engine.enabled_tools)
                lines = ["Tools:"] + [
                    ("* " if n in enabled else "  ") + n for n in names
                ]
                chat.append_block("\n".join(lines))
                return True
            if cmd == "/tools" and len(args) >= 2:
                sub = args[0].lower()
                name = " ".join(args[1:])
                if sub == "enable":
                    if self.engine.enabled_tools is None:
                        self.engine.enabled_tools = set()
                    self.engine.enabled_tools.add(name)
                    self._refresh_header()
                    ok(f"enabled tool -> {name}")
                    return True
                if sub == "disable":
                    if self.engine.enabled_tools is None:
                        # initialize to all tools then remove
                        self.engine.enabled_tools = set(
                            n
                            for n in (
                                t.get("name")
                                for t in self.engine._combined_tool_specs()
                            )
                            if n is not None
                        )
                    self.engine.enabled_tools.discard(name)
                    self._refresh_header()
                    ok(f"disabled tool -> {name}")
                    return True
            if cmd == "/todo" and args:
                sub = args[0].lower()
                if sub == "add" and len(args) > 1:
                    item = " ".join(args[1:])
                    self._todos.append(item)
                    ok(f"todo added -> {item}")
                    if self._show_todo:
                        self._render_todos(chat)
                    return True
                if sub == "remove" and len(args) > 1:
                    try:
                        idx = int(args[1]) - 1
                        if 0 <= idx < len(self._todos):
                            removed = self._todos.pop(idx)
                            ok(f"todo removed -> {removed}")
                            if self._show_todo:
                                self._render_todos(chat)
                        else:
                            err("index out of range")
                    except Exception:
                        err("usage: /todo remove <n>")
                    return True
                if sub in ("show", "hide"):
                    self._show_todo = sub == "show"
                    self.config.set("show_todo", self._show_todo)
                    self._render_todos(chat)
                    ok(f"todo -> {sub}")
                    return True
                err("usage: /todo add <item> | /todo remove <n> | /todo show|hide")
                return True
            if cmd == "/prune":
                # Prune conversation history to manage context length
                prune_count = 10  # Default number of messages to keep
                if args:
                    try:
                        prune_count = int(args[0])
                    except Exception:
                        err("prune count must be an integer")
                        return True

                original_count = len(self.messages)
                if original_count <= prune_count:
                    ok(
                        f"No pruning needed. Current: {original_count} messages, keep: {prune_count}"
                    )
                    return True

                # Keep the system message (if present) and the last N messages
                pruned_messages = []
                if self.messages and self.messages[0].get("role") == "system":
                    pruned_messages.append(self.messages[0])
                    # Keep last N-1 messages (since we kept system message)
                    pruned_messages.extend(self.messages[-(prune_count - 1) :])
                else:
                    # Keep last N messages
                    pruned_messages = self.messages[-prune_count:]

                removed_count = original_count - len(pruned_messages)
                self.messages = pruned_messages

                ok(
                    f"Pruned {removed_count} messages. Kept {len(pruned_messages)} messages."
                )
                return True
                ok(
                    "Commands:\n"
                    "/help\n"
                    "/model <name>\n"
                    "/provider <openai|anthropic|ollama>\n"
                    "/temp <float>\n"
                    "/system <text>\n"
                    "/auto <on|off>\n"
                    "/rounds <n>\n"
                    "/parallel <on|off>\n"
                    "/parallel limit <n>\n"
                    "/timeout <seconds>\n"
                    "/tools\n"
                    "/tools enable <name>\n"
                    "/tools disable <name>\n"
                )
                return True
            if cmd == "/model" and args:
                self._apply_provider_config(model=" ".join(args))
                ok(f"model set -> {' '.join(args)}")
                return True
            if cmd == "/provider" and args:
                prov = args[0].lower()
                if prov not in ("openai", "anthropic", "ollama"):
                    err("provider must be 'openai', 'anthropic', or 'ollama'")
                    return True
                try:
                    cfg = ProviderConfig(
                        model=self.provider.cfg.model,
                        api_key=self.provider.cfg.api_key,
                        base_url=self.provider.cfg.base_url,
                        temperature=self.provider.cfg.temperature,
                        system_prompt=self.provider.cfg.system_prompt,
                    )
                    new_provider = ProviderFactory.create(prov, cfg)
                    self.provider = new_provider
                    self.engine.provider = new_provider
                    ok(f"provider -> {prov}")
                except Exception as e:
                    err(f"failed to switch provider: {str(e)}")
                return True
            if cmd == "/temp" and args:
                try:
                    t = float(args[0])
                except Exception:
                    err("temp must be a float")
                    return True
                self._apply_provider_config(temperature=t)
                ok(f"temperature set -> {t}")
                return True
            if cmd == "/system" and args:
                text = " ".join(args)
                self._apply_provider_config(system=text)
                ok("system prompt updated")
                return True
            if cmd == "/auto" and args:
                val = args[0].lower()
                self.auto_continue = val in ("on", "true", "1", "yes")
                ok(f"auto-continue -> {self.auto_continue}")
                return True
            if cmd == "/rounds" and args:
                try:
                    n = int(args[0])
                except Exception:
                    err("rounds must be an integer")
                    return True
                self.max_rounds = max(1, n)
                ok(f"max rounds -> {self.max_rounds}")
                return True
            if cmd == "/parallel" and args:
                if args[0] == "limit" and len(args) > 1:
                    try:
                        n = int(args[1])
                    except Exception:
                        err("parallel limit must be an integer")
                        return True
                    self.engine.concurrency_limit = max(1, n)
                    ok(f"concurrency limit -> {self.engine.concurrency_limit}")
                    return True
                else:
                    val = args[0].lower()
                    if val in ("on", "off"):
                        # 'on' removes limit; 'off' sets to 1
                        self.engine.concurrency_limit = None if val == "on" else 1
                        ok(f"parallel -> {val}")
                        return True
            if cmd == "/timeout" and args:
                try:
                    secs = float(args[0])
                except Exception:
                    err("timeout must be a number (seconds)")
                    return True
                self.engine.tool_timeout = max(1.0, secs)
                ok(f"tool timeout -> {self.engine.tool_timeout}s")
                return True
            if cmd == "/tools":
                names = [
                    t.get("name", "")
                    for t in self.engine._combined_tool_specs()
                    if t.get("name") is not None
                ]
                if self.engine.enabled_tools is None:
                    enabled = set(names)
                else:
                    enabled = set(self.engine.enabled_tools)
                lines = ["Tools:"] + [
                    ("* " if n in enabled else "  ") + n for n in names
                ]
                chat.append_block("\n".join(lines))
                return True
            if cmd == "/tools" and len(args) >= 2:
                sub = args[0].lower()
                name = " ".join(args[1:])
                if sub == "enable":
                    if self.engine.enabled_tools is None:
                        self.engine.enabled_tools = set()
                    self.engine.enabled_tools.add(name)
                    ok(f"enabled tool -> {name}")
                    return True
                if sub == "disable":
                    if self.engine.enabled_tools is None:
                        # initialize to all tools then remove
                        self.engine.enabled_tools = set(
                            n
                            for n in (
                                t.get("name")
                                for t in self.engine._combined_tool_specs()
                            )
                            if n is not None
                        )
                    self.engine.enabled_tools.discard(name)
                    ok(f"disabled tool -> {name}")
                    return True
        except Exception as e:
            logger.error(f"Command handling failed: {e}")
            chat.append_block(f"[error] command failed: {str(e)}")
            return True
        return False

    async def on_input_submitted(self, event: Any) -> None:
        try:
            prompt = event.value.strip()
            # Skip empty submissions
            if not prompt:
                return

            # Clear input
            try:
                event.input.value = ""
            except Exception as e:
                logger.warning(f"Failed to clear input: {e}")

            chat = self.query_one("#chat", ChatView)
            # Slash commands are handled locally
            if prompt.strip().startswith("/"):
                handled = self._handle_command(prompt, chat)
                if handled:
                    return

            # Queue the prompt so UI remains responsive and supports multiple pending
            # In test contexts, we may not have a running worker; fall back to direct run
            try:
                _ = asyncio.get_running_loop()
                use_queue = (
                    self._worker_task is not None and not self._worker_task.done()
                )
            except RuntimeError:
                use_queue = False
            if use_queue:
                await self._queue.put(prompt)
                self._pending_count += 1
                self._update_status(working=False)  # Update pending count
            else:
                # Direct execution fallback for tests
                chat.append_block(f"**You:**\n{prompt}")
                chat.append_hr()
                self.messages.append({"role": "user", "content": prompt})
                # Persist user prompt
                try:
                    self._session_store.add_event({
                        "event_type": "user_prompt",
                        "content": prompt,
                    })
                except Exception:
                    pass
                await self._run_auto_rounds(chat)
            try:
                title = f"ChatApp - provider={type(self.provider).__name__.replace('Provider', '').lower()} model={self.provider.cfg.model} temp={self.provider.cfg.temperature} auto={self.auto_continue} rounds={self.max_rounds} pending={self._pending_count}"
                self.sub_title = title
            except Exception:
                pass
            except Exception as e:
                logger.error(f"Error during stream processing: {e}")
                chat.append_block(f"**[ERROR]** Stream processing failed: {str(e)}")

        except Exception as e:
            logger.error(f"Unexpected error in on_input_submitted: {e}")
            try:
                error_chat = self.query_one("#chat", ChatView)
                error_chat.append_block(f"**[ERROR]** Unexpected error: {str(e)}")
            except Exception:
                pass  # If we can't even display the error, just log it


async def run_textual_chat(
    provider: Provider,
    python_tools,
    mcp_manager: Optional[McpManager] = None,
    initial_messages: Optional[List[Dict[str, Any]]] = None,
    initial_markdown: Optional[str] = None,
) -> None:
    app = ChatApp(
        provider=provider,
        mcp_manager=mcp_manager,
        initial_messages=initial_messages,
        initial_markdown=initial_markdown,
    )
    await app.run_async()
