from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from openai import AsyncOpenAI

from .base import Provider, ProviderConfig, ToolSpec

logger = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    def __init__(self, cfg: ProviderConfig):
        super().__init__(cfg)
        self.client = (
            AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
            if cfg.base_url
            else AsyncOpenAI(api_key=cfg.api_key)
        )

    async def list_tools_format(self, tools: List[ToolSpec]) -> Any:
        # OpenAI tool format is compatible with JSON schema function tools
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get(
                        "parameters",
                        {"type": "object", "properties": {}, "required": []},
                    ),
                },
            }
            for t in tools
        ]

    async def completions_stream(
        self, messages: List[Dict[str, Any]], tools: Optional[List[ToolSpec]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        try:
            tool_schema = await self.list_tools_format(tools or []) if tools else None
            # Prepend system prompt if provided and not already present
            msgs = list(messages)
            if self.cfg.system_prompt and not any(
                m.get("role") == "system" for m in msgs
            ):
                msgs = [{"role": "system", "content": self.cfg.system_prompt}] + msgs
            params: Dict[str, Any] = {
                "model": self.cfg.model,
                "messages": msgs,
                "stream": True,
            }
            if self.cfg.temperature is not None:
                params["temperature"] = self.cfg.temperature
            if tool_schema:
                params["tools"] = tool_schema

            try:
                stream = await self.client.chat.completions.create(**params)
            except Exception as e:
                logger.error(f"OpenAI API call failed: {e}")
                yield {"type": "text", "delta": f"[ERROR] API call failed: {str(e)}"}
                return

            # Buffers for incremental tool_calls (indexed by tool_call index)
            arg_buf: Dict[int, str] = {}
            name_buf: Dict[int, Optional[str]] = {}
            id_buf: Dict[int, Optional[str]] = {}
            emitted: Set[int] = set()

            try:
                async for event in stream:
                    try:
                        if (
                            not event
                            or not hasattr(event, "choices")
                            or not event.choices
                        ):
                            continue

                        choice = event.choices[0]
                        if (
                            not choice
                            or not hasattr(choice, "delta")
                            or not choice.delta
                        ):
                            continue

                        delta = choice.delta
                        # Text delta
                        if hasattr(delta, "content") and delta.content:
                            yield {"type": "text", "delta": delta.content}
                        # Tool call incremental updates
                        if hasattr(delta, "tool_calls") and delta.tool_calls:
                            for tc in delta.tool_calls:
                                try:
                                    idx = getattr(tc, "index", 0)
                                    # accumulate ids / names
                                    if hasattr(tc, "id") and tc.id:
                                        id_buf[idx] = tc.id
                                    func = getattr(tc, "function", None)
                                    if func is not None:
                                        if hasattr(func, "name") and func.name:
                                            name_buf[idx] = func.name
                                        if (
                                            hasattr(func, "arguments")
                                            and func.arguments
                                        ):
                                            arg_buf[idx] = arg_buf.get(idx, "") + (
                                                func.arguments or ""
                                            )
                                    # Try to emit only when we can parse full JSON
                                    if (
                                        idx not in emitted
                                        and idx in arg_buf
                                        and arg_buf[idx].strip()
                                    ):
                                        try:
                                            args_obj = json.loads(arg_buf[idx])
                                            name = (
                                                name_buf.get(idx)
                                                or f"unknown_tool_{idx}"
                                            )
                                            call_id = id_buf.get(idx) or f"call_{idx}"
                                            emitted.add(idx)
                                            yield {
                                                "type": "tool_call",
                                                "id": call_id,
                                                "name": name,
                                                "arguments": args_obj,
                                            }
                                        except json.JSONDecodeError as je:
                                            logger.debug(
                                                f"JSON decode error for tool call {idx}: {je}. Buffer: {arg_buf[idx]}"
                                            )
                                            continue  # wait for more deltas
                                        except Exception as e:
                                            logger.error(
                                                f"Error processing tool call {idx}: {e}"
                                            )
                                            continue
                                except Exception as e:
                                    logger.error(
                                        f"Error processing tool call delta: {e}"
                                    )
                                    continue
                    except Exception as e:
                        logger.error(f"Error processing stream event: {e}")
                        continue
            except Exception as e:
                logger.error(f"Error during stream processing: {e}")
                yield {
                    "type": "text",
                    "delta": f"[ERROR] Stream processing failed: {str(e)}",
                }

        except Exception as e:
            logger.error(f"Unexpected error in completions_stream: {e}")
            yield {"type": "text", "delta": f"[ERROR] Unexpected error: {str(e)}"}
        # End of stream

    def build_assistant_message(
        self, text: str, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        tc_formatted = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc.get("arguments", {})),
                },
            }
            for tc in tool_calls
        ]
        msg: Dict[str, Any] = {"role": "assistant", "content": text}
        if tc_formatted:
            msg["tool_calls"] = tc_formatted
        return msg

    def format_tool_result_message(
        self, tool_call_id: str, content: str
    ) -> Dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
