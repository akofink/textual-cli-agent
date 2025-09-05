from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

from anthropic import AsyncAnthropic

from .base import Provider, ProviderConfig, ToolSpec


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
                "input_schema": t.get("parameters", {"type": "object", "properties": {}, "required": []}),
            }
            for t in tools
        ]

    async def completions_stream(
        self, messages: List[Dict[str, Any]], tools: Optional[List[ToolSpec]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        # Convert messages to Anthropic format
        sys = self.cfg.system_prompt
        conv: List[Dict[str, Any]] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                sys = m["content"]
                continue
            content = m.get("content")
            # Anthropics expects a list of objects
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            conv.append({"role": role, "content": content})
        tool_schema = await self.list_tools_format(tools or []) if tools else None

        stream_params: Dict[str, Any] = {
            "model": self.cfg.model,
            "system": sys,
            "messages": conv,
        }
        if self.cfg.temperature is not None:
            stream_params["temperature"] = self.cfg.temperature
        if tool_schema:
            stream_params["tools"] = tool_schema
            stream_params["tool_choice"] = {"type": "auto"}

        with self.client.messages.stream(**stream_params) as stream:
            async for event in stream:
                et = event.type
                if et == "message_start":
                    continue
                if et == "content_block_start":
                    continue
                if et == "content_block_delta":
                    if event.delta.get("type") == "text_delta":
                        yield {"type": "text", "delta": event.delta.get("text", "")}
                if et == "tool_call":
                    # anthropic tool call events
                    name = event.name
                    args = event.arguments
                    yield {
                        "type": "tool_call",
                        "id": event.id,
                        "name": name,
                        "arguments": json.loads(args) if isinstance(args, str) else args,
                    }
        # End of stream

    def build_assistant_message(self, text: str, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Anthropic assistant message format includes tool calls in content blocks
        content: List[Dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc.get("arguments", {}),
            })
        return {"role": "assistant", "content": content}

    def format_tool_result_message(self, tool_call_id: str, content: str) -> Dict[str, Any]:
        return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_call_id, "content": content}]}
