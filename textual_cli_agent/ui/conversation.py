from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from .chat_view import ChatView
from .tool_manager import ToolManager

if TYPE_CHECKING:
    from .app import ChatApp

logger = logging.getLogger(__name__)


class ConversationController:
    """Manage streaming agent responses and tool interactions."""

    def __init__(self, app: "ChatApp", tool_manager: ToolManager) -> None:
        self.app = app
        self.tool_manager = tool_manager

    async def worker(self) -> None:
        chat = self.app.query_one("#chat", ChatView)
        while True:
            prompt = await self.app._queue.get()
            try:
                chat.append_block(f"**You:**\n{prompt}")
                chat.append_hr()
                self.app.messages.append({"role": "user", "content": prompt})
                try:
                    self.app._session_store.add_event({
                        "event_type": "user_prompt",
                        "content": prompt,
                    })
                except Exception:
                    pass
                await self.run_auto_rounds(chat)
            except Exception as exc:
                logger.error(f"Worker error: {exc}")
                chat.append_block(f"**[ERROR]** Worker error: {str(exc)}")
            finally:
                self.app._pending_count = max(0, self.app._pending_count - 1)
                try:
                    self.app.sub_title = self.app._status_title()
                except Exception:
                    pass
                self.app._update_status(working=False)

    async def run_auto_rounds(self, chat: ChatView) -> None:
        rounds = 0
        while True:
            if not self.app.auto_continue and rounds > 0:
                break

            had_tools_this_round = False
            text_buf = ""

            self.app._tool_turn_counter += 1
            current_turn_id = self.app._tool_turn_counter
            panel = self.app._get_tool_panel()
            if panel:
                try:
                    panel.start_turn(current_turn_id)
                except Exception as exc:
                    logger.debug(
                        f"Failed to start tool panel turn {current_turn_id}: {exc}"
                    )

            try:
                self.app.sub_title = "Working..."
            except Exception:
                pass

            self.app._update_status(working=True)
            async for chunk in self.app.engine.run_stream(self.app.messages):
                await asyncio.sleep(0)
                try:
                    ctype = chunk.get("type")
                    if ctype == "text":
                        text_buf = await self._handle_text_chunk(chunk, chat, text_buf)
                    elif ctype == "tool_call":
                        await self._handle_tool_call(chunk, chat)
                    elif ctype == "tool_result":
                        await self._handle_tool_result(chunk, chat)
                    elif ctype == "append_message":
                        self._handle_append_message(chunk, chat)
                    elif ctype == "round_complete":
                        if text_buf:
                            chat.append_block(text_buf)
                            text_buf = ""
                        chat.append_hr()
                        had_tools_this_round = bool(chunk.get("had_tool_calls", False))
                        break
                except Exception as exc:
                    logger.error(f"Error processing chunk {chunk}: {exc}")
                    chat.append_text(f"[ERROR] Processing error: {str(exc)}")
                    continue

            rounds += 1
            if not had_tools_this_round:
                break
            if rounds >= self.app.max_rounds:
                await self._handle_round_limit(chat)
                break
            try:
                self.app.sub_title = (
                    f"ChatApp - provider={type(self.app.provider).__name__.replace('Provider', '').lower()} "
                    f"model={self.app.provider.cfg.model} temp={self.app.provider.cfg.temperature} "
                    f"auto={self.app.auto_continue} rounds={self.app.max_rounds}"
                )
            except Exception:
                pass

    async def _handle_text_chunk(
        self, chunk: Dict[str, Any], chat: ChatView, buffer: str
    ) -> str:
        delta = chunk.get("delta", "")
        if not delta:
            return buffer
        if "[ERROR]" in delta:
            chat.append_text(delta)
            return buffer
        buffer += delta
        try:
            self.app._session_store.add_event({
                "event_type": "assistant_text",
                "content": delta,
            })
        except Exception:
            pass
        return buffer

    async def _handle_tool_call(self, chunk: Dict[str, Any], chat: ChatView) -> None:
        tool_name = chunk.get("name", "unknown_tool")
        parsed_args = self.tool_manager.parse_payload(chunk.get("arguments", {}))
        tool_id = chunk.get("id", "")
        if tool_id:
            already_recorded = tool_id in self.tool_manager.tool_calls_by_id
            self.tool_manager.record_tool_call(tool_id, tool_name, parsed_args)
            if not already_recorded:
                self.tool_manager.write_debug(
                    tool_id,
                    "call",
                    {"name": tool_name, "arguments": parsed_args},
                )
        try:
            call_args_preview = json.dumps(parsed_args)[:120]
        except Exception:
            call_args_preview = str(parsed_args)[:120]
        chat.append_block(f"[tool call] {tool_name} args: {call_args_preview}")

    async def _handle_tool_result(self, chunk: Dict[str, Any], chat: ChatView) -> None:
        tool_id = chunk.get("id", "")
        content = chunk.get("content", "")
        parsed_content = self.tool_manager.parse_payload(content)

        if tool_id:
            self.tool_manager.write_debug(tool_id, "result", {"content": content})
            self.tool_manager.record_tool_result(tool_id, parsed_content)

        result_summary = self.tool_manager.result_summary(parsed_content)
        chat.write(f"✅ Result: {result_summary}")
        chat.write("\n")
        try:
            self.app._session_store.add_event({
                "event_type": "tool_result",
                "id": tool_id,
                "content": content,
            })
        except Exception:
            pass

    def _handle_append_message(self, chunk: Dict[str, Any], chat: ChatView) -> None:
        message = chunk.get("message", {})
        if not message:
            return
        if message.get("role") == "assistant" and message.get("tool_calls"):
            calls = message.get("tool_calls") or []
            pretty_calls = []
            for call in calls:
                function_data = call.get("function") or {}
                call_id = call.get("id", "")
                call_name = function_data.get("name", "unknown_tool")
                raw_arguments = function_data.get("arguments")
                parsed_arguments = self.tool_manager.parse_payload(raw_arguments)
                pretty_calls.append({
                    "id": call_id,
                    "name": call_name,
                    "arguments": parsed_arguments,
                })
                if call_id:
                    already_recorded = call_id in self.tool_manager.tool_calls_by_id
                    self.tool_manager.record_tool_call(
                        call_id, call_name, parsed_arguments
                    )
                    if not already_recorded:
                        self.tool_manager.write_debug(
                            call_id,
                            "call",
                            {"name": call_name, "arguments": parsed_arguments},
                        )
            chat.append_block(f"[assistant tool_calls]\n{pretty_calls}")
        self.app.messages.append(message)

    async def _handle_round_limit(self, chat: ChatView) -> None:
        self.app.messages.append({
            "role": "user",
            "content": (
                "[SYSTEM] You have reached the maximum number of tool-calling rounds "
                f"({self.app.max_rounds}). Please provide a final response without "
                "using any more tools."
            ),
        })
        text_buf = ""
        try:
            self.app.sub_title = "Final response..."
        except Exception:
            pass
        self.app._update_status(working=True)
        async for chunk in self.app.engine.run_stream(self.app.messages):
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
            except Exception as exc:
                logger.error(f"Error processing final response chunk {chunk}: {exc}")
                continue
