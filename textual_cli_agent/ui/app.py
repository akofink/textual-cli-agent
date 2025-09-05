from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


class ChatView(Static):  # type: ignore[misc]
    can_focus = True

    def on_mount(self) -> None:
        self._buffer = ""

    def get_text(self) -> str:
        return self._buffer

    def append_text(self, text: str) -> None:
        # Append streaming text without forcing newlines between chunks
        self._buffer += text
        try:
            self.update(Markdown(self._buffer))
        except Exception as e:
            logger.error(f"Error updating markdown: {e}")
            # Fallback to plain text update
            try:
                self.update(self._buffer)
            except Exception:
                pass  # Can't update, just continue
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass

    def append_block(self, md: str) -> None:
        # Append as a block with a preceding newline when appropriate
        if self._buffer:
            if not self._buffer.endswith("\n"):
                self._buffer += "\n"
        self._buffer += md
        try:
            self.update(Markdown(self._buffer))
        except Exception as e:
            logger.error(f"Error updating markdown block: {e}")
            # Fallback to plain text update
            try:
                self.update(self._buffer)
            except Exception:
                pass  # Can't update, just continue
        try:
            self.scroll_end(animate=False)
        except Exception:
            pass


class ChatApp(App):  # type: ignore[misc]
    def action_copy_chat(self) -> None:
        try:
            import pyperclip  # type: ignore
        except Exception:
            pyperclip = None  # type: ignore

        try:
            chat: ChatView = self.query_one("#chat")
            text = chat.get_text()
        except Exception as e:
            logger.error(f"Error getting chat text: {e}")
            return

        if pyperclip:
            try:
                pyperclip.copy(text)  # type: ignore[attr-defined]
                return
            except Exception:
                pass
        # Fallback: write to a file
        try:
            with open("chat_export.txt", "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            logger.error(f"Error writing chat export file: {e}")

    CSS = """
    Screen { layout: vertical; }
    #chat { height: 1fr; overflow: auto; }
    #input { dock: bottom; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+y", "copy_chat", "Copy chat", show=True),
    ]

    def on_key(self, event: events.Key) -> None:
        # Ensure Ctrl+C / Ctrl+D always quit, even if widgets handle them differently
        if event.key in ("ctrl+q", "ctrl+d"):
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
        yield Vertical(
            ChatView(id="chat"),
            Input(
                placeholder="Type a message and press Enter", id="input", password=False
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        if self._initial_markdown:
            try:
                chat: ChatView = self.query_one("#chat")
                chat.append_block(self._initial_markdown)
            except Exception as e:
                logger.error(f"Error displaying initial markdown: {e}")

    async def on_input_submitted(self, event: Any) -> None:
        try:
            prompt = event.value
            # Ctrl+D/EOF produces empty string; treat as quit
            if prompt == "":
                await self.action_quit()
                return

            # Clear input
            try:
                event.input.value = ""
            except Exception as e:
                logger.warning(f"Failed to clear input: {e}")

            chat: ChatView = self.query_one("#chat")
            chat.append_block(f"**You:** {prompt}")
            # Append assistant header on a new line to separate visually from the prompt
            chat.append_block("")
            self.messages.append({"role": "user", "content": prompt})

            try:
                async for chunk in self.engine.run_stream(self.messages):
                    try:
                        ctype = chunk.get("type")
                        if ctype == "text":
                            delta = chunk.get("delta", "")
                            if delta:  # Only append non-empty deltas
                                chat.append_text(
                                    delta
                                )  # stream text with no extra spacing
                        elif ctype == "tool_call":
                            tool_name = chunk.get("name", "unknown_tool")
                            tool_args = chunk.get("arguments", {})
                            chat.append_block(f"[tool call] {tool_name}({tool_args})")
                        elif ctype == "tool_result":
                            content = chunk.get("content", "")
                            # Truncate very long tool results for display
                            if len(str(content)) > 1000:
                                content = str(content)[:1000] + "... (truncated)"
                            chat.append_block(f"[tool result] {content}")
                        elif ctype == "append_message":
                            # Engine is asking us to append a message to conversation to maintain correct provider format
                            message = chunk.get("message", {})
                            if message:
                                self.messages.append(message)
                        elif ctype == "round_complete":
                            chat.append_block("\n---")
                            break
                    except Exception as e:
                        logger.error(f"Error processing chunk {chunk}: {e}")
                        chat.append_text(f"[ERROR] Processing error: {str(e)}")
                        continue
            except Exception as e:
                logger.error(f"Error during stream processing: {e}")
                chat.append_block(f"**[ERROR]** Stream processing failed: {str(e)}")

        except Exception as e:
            logger.error(f"Unexpected error in on_input_submitted: {e}")
            try:
                error_chat: ChatView = self.query_one("#chat")
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
