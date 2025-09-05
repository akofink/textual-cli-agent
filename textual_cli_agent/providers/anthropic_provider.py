from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from anthropic import AsyncAnthropic

from .base import Provider, ProviderConfig, ToolSpec

logger = logging.getLogger(__name__)


class AnthropicProvider(Provider):
    def __init__(self, cfg: ProviderConfig):
        super().__init__(cfg)
        self.client = AsyncAnthropic(api_key=cfg.api_key)

    async def list_tools_format(self, tools: List[ToolSpec]) -> Any:
        # Anthropic tools are compatible with JSON schema
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get(
                    "parameters", {"type": "object", "properties": {}, "required": []}
                ),
            }
            for t in tools
        ]

    async def completions_stream(
        self, messages: List[Dict[str, Any]], tools: Optional[List[ToolSpec]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        try:
            # Convert messages to Anthropic format
            sys = self.cfg.system_prompt
            conv: List[Dict[str, Any]] = []
            for m in messages:
                try:
                    role = m.get("role", "user")
                    if role == "system":
                        sys = m.get("content", "")
                        continue
                    content = m.get("content")
                    if content is None:
                        logger.warning(f"Message missing content: {m}")
                        continue
                    # Anthropics expects a list of objects
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}]
                    conv.append({"role": role, "content": content})
                except Exception as e:
                    logger.error(f"Error processing message {m}: {e}")
                    continue

            if not conv:
                logger.error("No valid messages to process")
                yield {"type": "text", "delta": "[ERROR] No valid messages to process"}
                return

            tool_schema = await self.list_tools_format(tools or []) if tools else None

            stream_params: Dict[str, Any] = {
                "model": self.cfg.model,
                "messages": conv,
            }

            if sys:
                stream_params["system"] = sys

            if self.cfg.temperature is not None:
                stream_params["temperature"] = self.cfg.temperature
            if tool_schema:
                stream_params["tools"] = tool_schema
                stream_params["tool_choice"] = {"type": "auto"}

            try:
                async with self.client.messages.stream(**stream_params) as stream:
                    try:
                        async for event in stream:
                            try:
                                if not event or not hasattr(event, "type"):
                                    continue

                                et = event.type
                                if et == "message_start":
                                    continue
                                if et == "content_block_start":
                                    continue
                                if et == "content_block_delta":
                                    if hasattr(event, "delta") and event.delta:
                                        # Handle delta as dict-like object
                                        if (
                                            hasattr(event.delta, "type")
                                            and event.delta.type == "text_delta"
                                        ):
                                            text = getattr(event.delta, "text", "")
                                            if text:
                                                yield {"type": "text", "delta": text}
                                        elif (
                                            isinstance(event.delta, dict)
                                            and event.delta.get("type") == "text_delta"
                                        ):
                                            text = event.delta.get("text", "")
                                            if text:
                                                yield {"type": "text", "delta": text}
                                if et == "tool_call":
                                    # anthropic tool call events
                                    if hasattr(event, "name") and hasattr(event, "id"):
                                        name = event.name or "unknown_tool"
                                        args = getattr(event, "arguments", {})
                                        try:
                                            if isinstance(args, str):
                                                args = (
                                                    json.loads(args)
                                                    if args.strip()
                                                    else {}
                                                )
                                            yield {
                                                "type": "tool_call",
                                                "id": event.id,
                                                "name": name,
                                                "arguments": args,
                                            }
                                        except json.JSONDecodeError as je:
                                            logger.error(
                                                f"JSON decode error for tool call {event.id}: {je}"
                                            )
                                            yield {
                                                "type": "tool_call",
                                                "id": event.id,
                                                "name": name,
                                                "arguments": {},
                                            }
                            except Exception as e:
                                logger.error(f"Error processing stream event: {e}")
                                continue
                    except Exception as e:
                        logger.error(f"Error during stream iteration: {e}")
                        yield {
                            "type": "text",
                            "delta": f"[ERROR] Stream iteration failed: {str(e)}",
                        }
            except Exception as e:
                logger.error(f"Anthropic API call failed: {e}")
                yield {"type": "text", "delta": f"[ERROR] API call failed: {str(e)}"}
                return
        except Exception as e:
            logger.error(f"Unexpected error in completions_stream: {e}")
            yield {"type": "text", "delta": f"[ERROR] Unexpected error: {str(e)}"}
        # End of stream

    def build_assistant_message(
        self, text: str, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        # Anthropic assistant message format includes tool calls in content blocks
        content: List[Dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc.get("arguments", {}),
                }
            )
        return {"role": "assistant", "content": content}

    def format_tool_result_message(
        self, tool_call_id: str, content: str
    ) -> Dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_call_id, "content": content}
            ],
        }
