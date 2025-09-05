from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from openai import AsyncOpenAI

from .base import Provider, ProviderConfig, ToolSpec


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
        tool_schema = await self.list_tools_format(tools or []) if tools else None
        # Prepend system prompt if provided and not already present
        msgs = list(messages)
        if self.cfg.system_prompt and not any(m.get("role") == "system" for m in msgs):
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
        stream = await self.client.chat.completions.create(**params)
        # Buffers for incremental tool_calls (indexed by tool_call index)
        arg_buf: Dict[int, str] = {}
        name_buf: Dict[int, Optional[str]] = {}
        id_buf: Dict[int, Optional[str]] = {}
        emitted: Set[int] = set()
        async for event in stream:
            if event.choices and event.choices[0].delta:
                delta = event.choices[0].delta
                # Text delta
                if getattr(delta, "content", None):
                    yield {"type": "text", "delta": delta.content}
                # Tool call incremental updates
                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = getattr(tc, "index", 0)
                        # accumulate ids / names
                        if getattr(tc, "id", None):
                            id_buf[idx] = tc.id
                        func = getattr(tc, "function", None)
                        if func is not None:
                            if getattr(func, "name", None):
                                name_buf[idx] = func.name
                            if getattr(func, "arguments", None):
                                arg_buf[idx] = arg_buf.get(idx, "") + (
                                    func.arguments or ""
                                )
                        # Try to emit only when we can parse full JSON
                        if idx not in emitted and idx in arg_buf:
                            try:
                                args_obj = json.loads(arg_buf[idx])
                            except Exception:
                                continue  # wait for more deltas
                            name = name_buf.get(idx) or ""
                            call_id = id_buf.get(idx) or (f"call_{idx}")
                            emitted.add(idx)
                            yield {
                                "type": "tool_call",
                                "id": call_id,
                                "name": name,
                                "arguments": args_obj,
                            }
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
