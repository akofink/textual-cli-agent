from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, Static
from textual.containers import Vertical
from textual.binding import Binding
from textual import events
from rich.markdown import Markdown

from ..engine import AgentEngine
from ..providers.base import Provider
from ..mcp.client import McpManager


class ChatView(Static):
    def on_mount(self) -> None:
        self._buffer = ""

    def append_text(self, text: str) -> None:
        # Append streaming text without forcing newlines between chunks
        self._buffer += text
        self.update(Markdown(self._buffer))

    def append_block(self, md: str) -> None:
        # Append as a block with a preceding newline when appropriate
        if self._buffer:
            if not self._buffer.endswith("\n"):
                self._buffer += "\n"
        self._buffer += md
        self.update(Markdown(self._buffer))


class ChatApp(App):
    CSS = """
    Screen { layout: vertical; }
    #chat { height: 1fr; overflow: auto; }
    #input { dock: bottom; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+d", "quit", "Quit", show=False),
    ]

    def on_key(self, event: events.Key) -> None:
        # Ensure Ctrl+C / Ctrl+D always quit, even if widgets handle them differently
        if event.key in ("ctrl+c", "ctrl+d"):
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(ChatView(id="chat"), Input(placeholder="Type a message and press Enter", id="input", password=False))
        yield Footer()

    def on_mount(self) -> None:
        if self._initial_markdown:
            chat: ChatView = self.query_one("#chat")
            chat.append_block(self._initial_markdown)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value
        # Ctrl+D/EOF produces empty string; treat as quit
        if prompt == "":
            await self.action_quit()
            return
        event.input.value = ""
        chat: ChatView = self.query_one("#chat")
        chat.append_block(f"**You:** {prompt}")
        # Append assistant header on a new line to separate visually from the prompt
        chat.append_block("")
        self.messages.append({"role": "user", "content": prompt})

        async for chunk in self.engine.run_stream(self.messages):
            ctype = chunk.get("type")
            if ctype == "text":
                chat.append_text(chunk["delta"])  # stream text with no extra spacing
            elif ctype == "tool_call":
                chat.append_block(f"[tool call] {chunk['name']}({chunk.get('arguments', {})})")
            elif ctype == "tool_result":
                chat.append_block(f"[tool result] {chunk['content']}")
            elif ctype == "append_message":
                # Engine is asking us to append a message to conversation to maintain correct provider format
                self.messages.append(chunk["message"])
            elif ctype == "round_complete":
                chat.append_block("\n---")
                break


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
