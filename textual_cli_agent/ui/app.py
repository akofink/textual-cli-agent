from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import json
import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog
from textual.containers import Vertical
from textual.binding import Binding
from textual import events
from rich.markdown import Markdown
from rich.text import Text

from ..engine import AgentEngine
from ..providers.base import Provider
from ..mcp.client import McpManager

logger = logging.getLogger(__name__)


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

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #chat {
        height: 1fr;
        overflow: auto;
        border: solid $primary;
        scrollbar-background: $panel;
        scrollbar-color: $accent;
        scrollbar-corner-color: $panel;
        scrollbar-size: 1 1;
        text-wrap: wrap; /* ensure wrapping vs horizontal scroll */
        width: 96%; /* slightly narrower to prevent 1-char overflow in some terminals */
    }

    #input {
        dock: bottom;
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
    }
    """

    BINDINGS = [
        # Core navigation - keep Toad-like simplicity
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+d", "quit", "Quit", show=False),
        # Enhanced text interaction - Toad-inspired
        Binding("ctrl+y", "copy_chat", "Copy chat", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        # Enhanced navigation - smooth scrolling like Toad
        Binding("home", "scroll_home", "Top", show=True),
        Binding("end", "scroll_end", "Bottom", show=True),
        Binding("ctrl+home", "scroll_home", "Top", show=False),
        Binding("ctrl+end", "scroll_end", "Bottom", show=False),
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
        # Track tool calls by id to enhance result display
        self._tool_calls_by_id: Dict[str, Dict[str, Any]] = {}

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
                chat = self.query_one("#chat", ChatView)
                chat.append_block(self._initial_markdown)
            except Exception as e:
                logger.error(f"Error displaying initial markdown: {e}")

    async def _run_auto_rounds(self, chat: "ChatView") -> None:
        max_rounds = 6
        rounds = 0
        while True:
            had_tools_this_round = False
            text_buf = ""
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
                        chat.append_block(
                            f"[tool call]\nname: {tool_name}\nargs: {tool_args}"
                        )
                    elif ctype == "tool_result":
                        content = chunk.get("content", "")
                        tool_id = chunk.get("id", "")
                        header = "[tool result]"
                        if tool_id and tool_id in self._tool_calls_by_id:
                            meta = self._tool_calls_by_id[tool_id]
                            header = (
                                "[tool]\n"
                                f"name: {meta.get('name')}\n"
                                f"args: {meta.get('arguments')}\n"
                                "output:"
                            )
                        try:
                            parsed = json.loads(content)
                            content = json.dumps(parsed, indent=2, ensure_ascii=False)
                        except Exception:
                            pass
                        max_display = 8000
                        display = (
                            str(content)[:max_display] + "\n... (truncated in view)"
                            if len(str(content)) > max_display
                            else str(content)
                        )
                        chat.append_block(f"{header}\n{display}")
                        chat.append_hr()
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
            if not had_tools_this_round or rounds >= max_rounds:
                break

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

            chat = self.query_one("#chat", ChatView)
            # Show user prompt as its own block
            chat.append_block(f"**You:**\n{prompt}")
            chat.append_hr()
            self.messages.append({"role": "user", "content": prompt})

            try:
                await self._run_auto_rounds(chat)
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
