from __future__ import annotations

import json
import logging
import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from .providers.base import Provider, ToolSpec
from .tools import execute_tool, get_tool_specs
from .mcp.client import McpManager

logger = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, provider: Provider, mcp_manager: Optional[McpManager] = None):
        self.provider = provider
        self.mcp_manager = mcp_manager
        # Runtime-tunable settings
        self.tool_timeout: float = 60.0
        self.concurrency_limit: Optional[int] = None  # None = unbounded gather
        self.enabled_tools: Optional[set[str]] = None  # None = all tools

    def _combined_tool_specs(self) -> List[ToolSpec]:
        specs = get_tool_specs()
        if self.mcp_manager:
            specs.extend(self.mcp_manager.tool_specs())
        return specs

    async def run_stream(
        self, messages: List[Dict[str, Any]]
    ) -> AsyncIterator[Dict[str, Any]]:
        try:
            # Validate messages
            if not messages:
                logger.error("No messages provided to run_stream")
                yield {"type": "text", "delta": "[ERROR] No messages provided"}
                return

            for i, msg in enumerate(messages):
                if not isinstance(msg, dict):
                    logger.error(f"Message {i} is not a dictionary: {msg}")
                    yield {
                        "type": "text",
                        "delta": f"[ERROR] Invalid message format at index {i}",
                    }
                    return
                if "role" not in msg:
                    logger.error(f"Message {i} missing role: {msg}")
                    yield {
                        "type": "text",
                        "delta": f"[ERROR] Message missing role at index {i}",
                    }
                    return

            tools: List[ToolSpec] = []
            try:
                tools = self._combined_tool_specs()
                # Apply enabled_tools filter if configured
                if self.enabled_tools is not None:
                    tools = [t for t in tools if t.get("name") in self.enabled_tools]
            except Exception as e:
                logger.error(f"Error getting tool specs: {e}")
                # Continue with empty tools rather than failing completely

            assistant_text_parts: List[str] = []
            tool_calls: List[Dict[str, Any]] = []
            pending_tool_messages: List[Dict[str, Any]] = []
            # collect tool calls to execute concurrently at end
            scheduled_tools: List[Dict[str, Any]] = []
            had_tool_calls = False

            try:
                async for chunk in self.provider.completions_stream(
                    messages, tools=tools
                ):
                    try:
                        if not chunk or not isinstance(chunk, dict):
                            logger.warning(f"Invalid chunk received: {chunk}")
                            continue

                        chunk_type = chunk.get("type")
                        if chunk_type == "text":
                            delta = chunk.get("delta", "")
                            if delta:  # Only append non-empty deltas
                                assistant_text_parts.append(delta)
                            # Pass-through for UI
                            yield chunk
                        elif chunk_type == "tool_call":
                            had_tool_calls = True
                            tool_calls.append(chunk)
                            name = chunk.get("name", "unknown_tool")
                            args = chunk.get("arguments", {})
                            tool_call_id = chunk.get("id", f"call_{len(tool_calls)}")

                            # Schedule tool for concurrent execution; don't await inline
                            scheduled_tools.append({
                                "id": tool_call_id,
                                "name": name,
                                "arguments": args,
                            })
                    except Exception as e:
                        logger.error(f"Error processing chunk {chunk}: {e}")
                        yield {
                            "type": "text",
                            "delta": f"[ERROR] Processing error: {str(e)}",
                        }
                        continue

            except Exception as e:
                logger.error(f"Error in provider stream: {e}")
                yield {
                    "type": "text",
                    "delta": f"[ERROR] Provider stream failed: {str(e)}",
                }

            # Execute any scheduled tools concurrently, then build tool result messages
            if scheduled_tools:
                try:
                    sem = (
                        asyncio.Semaphore(self.concurrency_limit)
                        if self.concurrency_limit and self.concurrency_limit > 0
                        else None
                    )

                    async def _run_with_limit(t):
                        if sem is None:
                            return await self._execute_tool_safely(
                                t["name"], t["arguments"]
                            )
                        async with sem:
                            return await self._execute_tool_safely(
                                t["name"], t["arguments"]
                            )

                    results = await asyncio.gather(
                        *[_run_with_limit(t) for t in scheduled_tools],
                        return_exceptions=False,
                    )
                    for t, res in zip(scheduled_tools, results):
                        try:
                            result_str = json.dumps(res, ensure_ascii=False)
                        except (TypeError, ValueError) as e:
                            logger.error(f"Error serializing tool result: {e}")
                            result_str = json.dumps({
                                "error": f"Result serialization failed: {str(e)}"
                            })
                        try:
                            tool_msg = self.provider.format_tool_result_message(
                                t["id"], result_str
                            )
                            pending_tool_messages.append(tool_msg)
                        except Exception:
                            pending_tool_messages.append({
                                "role": "tool",
                                "tool_call_id": t["id"],
                                "content": result_str,
                            })
                        # Also surface to UI (does not affect provider message ordering)
                        yield {
                            "type": "tool_result",
                            "id": t["id"],
                            "content": result_str,
                        }
                except Exception as e:
                    logger.error(f"Error executing scheduled tools: {e}")

            # After tools (if any), append assistant message with accumulated text and tool-calls (metadata)
            try:
                final_text = "".join(assistant_text_parts)
                assistant_msg = self.provider.build_assistant_message(
                    final_text, tool_calls
                )
                yield {"type": "append_message", "message": assistant_msg}
            except Exception as e:
                logger.error(f"Error building assistant message: {e}")
                # Fallback message
                assistant_msg = {
                    "role": "assistant",
                    "content": "".join(assistant_text_parts),
                }
                yield {"type": "append_message", "message": assistant_msg}

            # Append any pending tool result messages AFTER the assistant message that contains tool_calls
            for tmsg in pending_tool_messages:
                yield {"type": "append_message", "message": tmsg}

            yield {"type": "round_complete", "had_tool_calls": had_tool_calls}

        except Exception as e:
            logger.error(f"Unexpected error in run_stream: {e}")
            yield {"type": "text", "delta": f"[ERROR] Unexpected error: {str(e)}"}
            yield {"type": "round_complete", "had_tool_calls": False}

    async def _execute_tool_safely(
        self, name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a tool with comprehensive error handling and timeouts."""
        try:
            # Validate tool arguments
            if not isinstance(args, dict):
                return {
                    "error": f"Tool arguments must be a dictionary, got {type(args).__name__}"
                }

            # Apply timeout to prevent hanging
            try:
                result = await asyncio.wait_for(
                    self._execute_tool_internal(name, args),
                    timeout=60.0,  # 60 second timeout for tool execution
                )
                return result
            except asyncio.TimeoutError:
                logger.error(f"Tool {name} timed out after 60 seconds")
                return {"error": f"Tool '{name}' execution timed out"}

        except Exception as e:
            logger.error(f"Error in _execute_tool_safely for {name}: {e}")
            return {"error": f"Tool execution error: {str(e)}"}

    async def _execute_tool_internal(
        self, name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Internal tool execution with MCP fallback."""
        try:
            # Try MCP first if available
            if self.mcp_manager and any(
                t["name"] == name for t in self.mcp_manager.tool_specs()
            ):
                try:
                    return await self.mcp_manager.execute(name, args)
                except Exception as e:
                    logger.error(f"MCP tool {name} failed: {e}")
                    # Fall back to built-in tools

            # Execute built-in tool
            return await execute_tool(name, args)

        except Exception as e:
            logger.error(f"Tool {name} execution failed: {e}")
            return {"error": str(e)}
