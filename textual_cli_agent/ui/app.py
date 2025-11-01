from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, LoadingIndicator, Static

from ..config import ConfigManager
from ..engine import AgentEngine
from ..mcp.client import McpManager
from ..providers.base import Provider
from ..session_store import SessionStore
from .actions.clipboard import ClipboardActionsMixin
from .actions.general import GeneralActionsMixin
from .actions.panels import PanelActionsMixin
from .actions.session import SessionActionsMixin
from .actions.theme import ThemeActionsMixin
from .actions.todo import TodoActionsMixin
from .chat_commands import ChatCommands
from .chat_header import ChatHeader
from .chat_view import ChatView
from .command_processor import CommandProcessor
from .conversation import ConversationController
from .provider_config import ProviderConfigMixin
from .tool_manager import ToolManager
from .tool_panel import ToolPanel
from .todo_panel import TodoPanel

logger = logging.getLogger(__name__)


class ChatApp(
    ThemeActionsMixin,
    PanelActionsMixin,
    ClipboardActionsMixin,
    TodoActionsMixin,
    SessionActionsMixin,
    GeneralActionsMixin,
    ProviderConfigMixin,
    App,  # type: ignore[misc]
):
    provider: Provider
    engine: AgentEngine
    _tool_panel_widget: Optional[ToolPanel]
    _todo_panel_widget: Optional[TodoPanel]

    COMMANDS = App.COMMANDS | {ChatCommands}

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+c", "copy", "Copy", show=True),
        Binding("ctrl+shift+c", "copy_tool_details", "Copy Tool", show=True),
        Binding("f2", "toggle_tools", "Tools", show=True),
        Binding("f3", "toggle_todo_panel", "Todos", show=True),
        Binding("ctrl+y", "copy_chat", "Copy", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("home", "scroll_home", "Top", show=False),
        Binding("end", "scroll_end", "Bottom", show=False),
    ]

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

        self.config = ConfigManager()
        self._session_store = SessionStore(self.config)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_path = self._session_store.start_session(self._session_id)

        self.auto_continue = self.config.get("auto_continue", True)
        self.max_rounds = self.config.get("max_rounds", 15)
        self._worker_task: Optional[asyncio.Task] = None
        self._pending_count = 0
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tool_turn_counter = 0
        self._todos: List[str] = []
        self._show_todo = self.config.get("show_todo", False)
        self._tool_panel_widget = None
        self._todo_panel_widget = None

        self.tool_manager = ToolManager(self._get_tool_panel, self._session_store)
        self._command_processor = CommandProcessor(self)
        self._conversation = ConversationController(self, self.tool_manager)

        self._apply_saved_provider_config()

        saved_theme = self.config.get("theme")
        if saved_theme:
            try:
                self.theme = saved_theme
            except Exception as exc:
                logger.warning(f"Failed to apply saved theme '{saved_theme}': {exc}")

    def on_key(self, event: events.Key) -> None:
        if event.key == "ctrl+q":
            event.prevent_default()
            event.stop()
            self.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in {"quit_button", "header_quit_button"}:
            event.stop()
            self.exit()

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

    def _set_loading_indicator(self, busy: bool) -> None:
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
            pass
        self._set_loading_indicator(busy)

    def on_mount(self) -> None:
        try:
            self._refresh_header()
        except Exception:
            pass
        self._update_status(working=False)

        try:
            self.query_one("#input", Input).focus()
        except Exception:
            pass

        if self._initial_markdown:
            try:
                chat = self.query_one("#chat", ChatView)
                chat.append_block(self._initial_markdown)
            except Exception as exc:
                logger.error(f"Error displaying initial markdown: {exc}")

        try:
            loop = asyncio.get_running_loop()
            if self._worker_task is None:
                self._worker_task = loop.create_task(self._conversation.worker())
        except RuntimeError:
            pass
        except Exception as exc:
            logger.error(f"Failed to start worker: {exc}")

    async def on_input_submitted(self, event: Any) -> None:
        try:
            prompt = event.value.strip()
            if not prompt:
                return

            try:
                event.input.value = ""
            except Exception as exc:
                logger.warning(f"Failed to clear input: {exc}")

            chat = self.query_one("#chat", ChatView)
            if prompt.startswith("/"):
                if self._command_processor.handle(prompt, chat):
                    return

            use_queue = False
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
                self._update_status(working=False)
            else:
                chat.append_block(f"**You:**\n{prompt}")
                chat.append_hr()
                self.messages.append({"role": "user", "content": prompt})
                try:
                    self._session_store.add_event({
                        "event_type": "user_prompt",
                        "content": prompt,
                    })
                except Exception:
                    pass
                await self._conversation.run_auto_rounds(chat)

            try:
                self.sub_title = self._status_title()
            except Exception:
                pass
        except Exception as exc:
            logger.error(f"Unexpected error in on_input_submitted: {exc}")
            try:
                error_chat = self.query_one("#chat", ChatView)
                error_chat.append_block(f"**[ERROR]** Unexpected error: {str(exc)}")
            except Exception:
                pass


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
