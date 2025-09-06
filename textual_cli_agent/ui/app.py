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
from ..providers.base import Provider, ProviderConfig, ProviderFactory
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
    # TODO: Tool call logs sometimes appear after tool results in UI; investigate event ordering.
    # TODO: Ensure chat_export*.txt files are always gitignored and never committed.

    provider: Provider
    engine: AgentEngine

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

    Header Title {
        content-align: left middle;
    }

    #chat {
        height: 1fr;
        overflow-y: auto;
        overflow-x: hidden;
        border: solid $primary;
        scrollbar-background: $panel;
        scrollbar-color: $accent;
        scrollbar-corner-color: $panel;
        scrollbar-size: 1 1;
        text-wrap: wrap; /* ensure wrapping vs horizontal scroll */
        width: 100%;
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
        # Runtime toggles
        self.auto_continue: bool = True
        self.max_rounds: int = 6
        # Background processing and queuing
        self._worker_task: Optional[asyncio.Task] = None
        self._pending_count: int = 0
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        # Tool call/result ordering tracking
        self._displayed_tool_calls: set[str] = set()
        # Simple TODO list pane
        self._todos: List[str] = []
        self._show_todo: bool = False

    def _status_title(self) -> str:
        return (
            f"ChatApp - provider={type(self.provider).__name__.replace('Provider', '').lower()} "
            f"model={self.provider.cfg.model} temp={self.provider.cfg.temperature} "
            f"auto={self.auto_continue} rounds={self.max_rounds} pending={self._pending_count}"
        )

    def _refresh_header(self) -> None:
        try:
            self.query_one("#hdr", Header).sub_title = self._status_title()
        except Exception:
            pass

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
        except Exception as e:
            logger.error(f"Error rendering todos: {e}")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, id="hdr")
        yield Vertical(
            ChatView(id="chat"),
            Input(
                placeholder="Type a message and press Enter (/help for commands)",
                id="input",
                password=False,
            ),
        )
        yield Footer()

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
                    self.query_one("#hdr", Header).sub_title = title
                except Exception:
                    pass

    def on_mount(self) -> None:
        # Update header title with live status
        try:
            self._refresh_header()
        except Exception:
            pass
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
            # Show working indicator
            try:
                self.query_one("#hdr", Header).sub_title = "Working..."
            except Exception:
                pass
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
                        # Render call with explicit id for mapping clarity
                        chat.append_block(
                            f"[tool call]\nid: {tool_id}\nname: {tool_name}\nargs: {tool_args}"
                        )
                    elif ctype == "tool_result":
                        content = chunk.get("content", "")
                        tool_id = chunk.get("id", "")
                        header = "[tool result]"
                        if tool_id and tool_id in self._tool_calls_by_id:
                            meta = self._tool_calls_by_id[tool_id]
                            # If call not yet shown (rare), print it now before result
                            if tool_id not in self._displayed_tool_calls:
                                chat.append_block(
                                    f"[tool call]\nid: {tool_id}\nname: {meta.get('name')}\nargs: {meta.get('arguments')}"
                                )
                                self._displayed_tool_calls.add(tool_id)
                            header = (
                                "[tool]\n"
                                f"id: {tool_id}\n"
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
            if not had_tools_this_round or rounds >= self.max_rounds:
                break
            # Restore header subtitle to status between rounds
            try:
                title = f"ChatApp - provider={type(self.provider).__name__.replace('Provider', '').lower()} model={self.provider.cfg.model} temp={self.provider.cfg.temperature} auto={self.auto_continue} rounds={self.max_rounds}"
                self.query_one("#hdr", Header).sub_title = title
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
                )
                return True
            if cmd == "/model" and args:
                self._apply_provider_config(model=" ".join(args))
                self._refresh_header()
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
                    self._render_todos(chat)
                    ok(f"todo -> {sub}")
                    return True
                err("usage: /todo add <item> | /todo remove <n> | /todo show|hide")
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
            else:
                # Direct execution fallback for tests
                chat.append_block(f"**You:**\n{prompt}")
                chat.append_hr()
                self.messages.append({"role": "user", "content": prompt})
                await self._run_auto_rounds(chat)
            try:
                title = f"ChatApp - provider={type(self.provider).__name__.replace('Provider', '').lower()} model={self.provider.cfg.model} temp={self.provider.cfg.temperature} auto={self.auto_continue} rounds={self.max_rounds} pending={self._pending_count}"
                self.query_one("#hdr", Header).sub_title = title
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
