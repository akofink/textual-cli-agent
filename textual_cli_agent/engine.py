from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

from .providers.base import Provider, ToolSpec
from .tools import execute_tool, get_tool_specs
from .mcp.client import McpManager


class AgentEngine:
    def __init__(self, provider: Provider, mcp_manager: Optional[McpManager] = None):
        self.provider = provider
        self.mcp_manager = mcp_manager

    def _combined_tool_specs(self) -> List[ToolSpec]:
        specs = get_tool_specs()
        if self.mcp_manager:
            specs.extend(self.mcp_manager.tool_specs())
        return specs

    async def run_stream(
        self, messages: List[Dict[str, Any]]
    ) -> AsyncIterator[Dict[str, Any]]:
        tools: List[ToolSpec] = self._combined_tool_specs()
        assistant_text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        had_tool_calls = False

        async for chunk in self.provider.completions_stream(messages, tools=tools):
            if chunk.get("type") == "text":
                assistant_text_parts.append(chunk.get("delta", ""))
                # Pass-through for UI
                yield chunk
            elif chunk.get("type") == "tool_call":
                had_tool_calls = True
                tool_calls.append(chunk)
                name = chunk["name"]
                args = chunk.get("arguments", {})
                try:
                    if self.mcp_manager and any(
                        t["name"] == name for t in self.mcp_manager.tool_specs()
                    ):
                        result = await self.mcp_manager.execute(name, args)
                    else:
                        result = await execute_tool(name, args)
                except Exception as e:
                    result = {"error": str(e)}
                result_str = json.dumps(result, ensure_ascii=False)
                # Provide provider-formatted tool result message to append
                tool_msg = self.provider.format_tool_result_message(
                    chunk["id"], result_str
                )
                yield {"type": "append_message", "message": tool_msg}
                # Also surface to UI
                yield {"type": "tool_result", "id": chunk["id"], "content": result_str}

        # After stream ends, append assistant message with accumulated text and tool-calls (metadata)
        final_text = "".join(assistant_text_parts)
        assistant_msg = self.provider.build_assistant_message(final_text, tool_calls)
        yield {"type": "append_message", "message": assistant_msg}
        yield {"type": "round_complete", "had_tool_calls": had_tool_calls}
