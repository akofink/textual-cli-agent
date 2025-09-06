from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import json
import asyncio
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog, Static
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from textual import events
from textual.command import Hit, Hits, Provider as CommandProvider
from functools import partial
from rich.markdown import Markdown
from rich.text import Text

from ..engine import AgentEngine
from ..providers.base import Provider, ProviderConfig, ProviderFactory
from ..mcp.client import McpManager
from ..config import ConfigManager
from .tool_panel import ToolPanel
from .todo_panel import TodoPanel

logger = logging.getLogger(__name__)


class ChatCommands(CommandProvider):
    """Command provider for chat application commands."""

    async def search(self, query: str) -> Hits:
        """Search for matching commands."""
        matcher = self.matcher(query)

        commands = [
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
        lines = []
        try:
            # Access the internal lines if possible for text extraction
            if hasattr(self, "_lines"):
                for line in self._lines:
                    if hasattr(line, "plain"):
                        lines.append(line.plain)
                    else:
                        lines.append(str(line))
            else:
                # Fallback to current text buffer
                lines.append(self._current_text)
        except Exception:
            lines.append(self._current_text)
        return "\n".join(lines)

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


class ChatApp(App):  # type: ignore[misc]
    # TODO: Tool call logs sometimes appear after tool results in UI; investigate event ordering.
    # TODO: Ensure chat_export*.txt files are always gitignored and never committed.

    provider: Provider
    engine: AgentEngine

    # Add our custom command provider to the command palette
    COMMANDS = App.COMMANDS | {ChatCommands}

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

    .status {
        dock: bottom;
        height: 1;
        background: $accent;
        color: $text;
        text-align: center;
        padding: 0 1;
        width: 100%;
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
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("ctrl+d", "toggle_dark", "Theme", show=True),
        # Keep most common actions as shortcuts
        Binding("f2", "toggle_tools", "Tools", show=True),
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
            if prov_name in ("openai", "anthropic"):
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

                if saved_provider and saved_provider in ("openai", "anthropic"):
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

    def on_key(self, event: events.Key) -> None:
        # Ensure Ctrl+C / Ctrl+D always quit, even if widgets handle them differently
        if event.key in ("ctrl+c", "ctrl+q", "ctrl+d"):
            event.prevent_default()
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

        # Debug file setup
        self._debug_dir = Path(".textual-debug")
        self._debug_dir.mkdir(exist_ok=True)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Runtime toggles - load from config with defaults
        self.auto_continue: bool = self.config.get("auto_continue", True)
        self.max_rounds: int = self.config.get("max_rounds", 15)
        # Background processing and queuing
        self._worker_task: Optional[asyncio.Task] = None
        self._pending_count: int = 0
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        # Tool call/result ordering tracking
        self._displayed_tool_calls: set[str] = set()
        # Simple TODO list pane
        self._todos: List[str] = []
        self._show_todo: bool = self.config.get("show_todo", False)

        # Apply any saved provider config overrides
        self._apply_saved_provider_config()

        # Apply saved theme
        saved_theme = self.config.get("theme")
        if saved_theme:
            self.theme = saved_theme

    def _write_tool_debug(
        self, tool_id: str, event_type: str, data: Dict[str, Any]
    ) -> None:
        """Write detailed tool information to debug JSON file."""
        try:
            debug_file = self._debug_dir / f"tools_{self._session_id}.json"
            timestamp = datetime.now().isoformat()

            debug_entry = {
                "timestamp": timestamp,
                "tool_id": tool_id,
                "event_type": event_type,
                "data": data,
            }

            # Append to debug file
            if debug_file.exists():
                with open(debug_file, "r") as f:
                    entries = json.load(f)
            else:
                entries = []

            entries.append(debug_entry)

            with open(debug_file, "w") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
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
        """Toggle dark/light theme and save preference."""
        # Let Textual do the theme toggle
        super().action_toggle_dark()
        # Save the new theme to config
        self.config.set("theme", self.theme)

    def action_copy_chat(self) -> None:
        """Enhanced copy functionality inspired by Toad's text interaction."""
        try:
            import pyperclip  # type: ignore
        except Exception:
            pyperclip = None  # type: ignore

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

        success = False
        if pyperclip:
            try:
                pyperclip.copy(text)  # type: ignore[attr-defined]
                success = True
                # Visual feedback - could add a toast notification here
            except Exception:
                pass

        # Enhanced fallback: write to a file with better naming
        if not success:
            try:
                from datetime import datetime

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"chat_export_{timestamp}.txt"
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(text)
                # Could log success to chat view here
            except Exception as e:
                logger.error(f"Error writing chat export file: {e}")
                self.bell()  # Audio feedback for error

    def action_help_panel(self) -> None:
        try:
            chat = self.query_one("#chat", ChatView)
            chat.append_block(
                "[help]\n"
                "Shortcuts:\n"
                "  Ctrl+P  Command palette (search all commands)\n"
                "  Ctrl+D  Toggle theme\n"
                "  F2      Toggle Tools panel\n"
                "  Ctrl+Y  Copy chat\n"
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
        """Toggle the tool panel visibility."""
        try:
            tool_panel = self.query_one("#tool_panel", ToolPanel)
            tool_panel.toggle_visibility()
        except Exception as e:
            logger.error(f"Error toggling tool panel: {e}")

    def action_toggle_todo_panel(self) -> None:
        """Toggle the todo panel visibility."""
        try:
            todo_panel = self.query_one("#todo_panel", TodoPanel)
            todo_panel.toggle_visibility()
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

    def _update_status(self, working: bool = False) -> None:
        """Update the footer status bar with current state."""
        try:
            status_bar = self.query_one("#status_bar", Static)
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
            try:
                todo_panel = self.query_one("#todo_panel", TodoPanel)
                todo_panel.update_todos(self._todos)
            except Exception:
                pass  # Todo panel might not be mounted
        except Exception as e:
            logger.error(f"Error rendering todos: {e}")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, id="hdr")
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
            ToolPanel(),
            TodoPanel(),
            id="content_area",
        )
        yield Static("Idle", id="status_bar", classes="status")
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

            # Start new turn in tool panel
            try:
                tool_panel = self.query_one("#tool_panel", ToolPanel)
                tool_panel.start_turn(rounds + 1)
            except Exception:
                pass  # Tool panel might not be mounted

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
                    elif ctype == "tool_call":
                        tool_name = chunk.get("name", "unknown_tool")
                        tool_args = chunk.get("arguments", {})
                        tool_id = chunk.get("id", "")
                        if tool_id:
                            self._tool_calls_by_id[tool_id] = {
                                "name": tool_name,
                                "arguments": tool_args,
                            }
                            self._displayed_tool_calls.add(tool_id)

                            # Update tool panel
                            try:
                                tool_panel = self.query_one("#tool_panel", ToolPanel)
                                tool_panel.add_tool_call(tool_id, tool_name, tool_args)
                            except Exception:
                                pass  # Tool panel might not be mounted

                            # Write detailed info to debug file
                            self._write_tool_debug(
                                tool_id,
                                "call",
                                {"name": tool_name, "arguments": tool_args},
                            )

                        # Display simple clickable version in chat
                        # Using a simple format that can be clicked to show in tool panel
                        chat.write(f"🔧 {tool_name} called")
                        chat.write("\n")
                    elif ctype == "tool_result":
                        content = chunk.get("content", "")
                        tool_id = chunk.get("id", "")

                        # Write detailed result to debug file
                        if tool_id:
                            self._write_tool_debug(
                                tool_id, "result", {"content": content}
                            )

                        # Display simple result indicator in chat
                        result_summary = self._get_result_summary(content)
                        chat.write(f"✅ Result: {result_summary}")
                        chat.write("\n")

                        # Update tool panel with result
                        if tool_id:
                            try:
                                tool_panel = self.query_one("#tool_panel", ToolPanel)
                                tool_panel.update_tool_result(tool_id, result=content)
                            except Exception:
                                pass  # Tool panel might not be mounted
                    elif ctype == "append_message":
                        message = chunk.get("message", {})
                        if message:
                            if message.get("role") == "assistant" and message.get(
                                "tool_calls"
                            ):
                                calls = message.get("tool_calls") or []
                                pretty_calls = [
                                    {
                                        "id": c.get("id"),
                                        "name": (c.get("function") or {}).get("name"),
                                        "arguments": (c.get("function") or {}).get(
                                            "arguments"
                                        ),
                                    }
                                    for c in calls
                                ]
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
                    "/provider <openai|anthropic>\n"
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
                if prov not in ("openai", "anthropic"):
                    err("provider must be 'openai' or 'anthropic'")
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
                    "/provider <openai|anthropic>\n"
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
                if prov not in ("openai", "anthropic"):
                    err("provider must be 'openai' or 'anthropic'")
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
