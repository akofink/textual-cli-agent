from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

try:
    from anthropic import AsyncAnthropic  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    AsyncAnthropic = None  # type: ignore

from .base import Provider, ProviderConfig, ToolSpec
from ..error_handler import api_error_handler
from ..context_manager import context_manager

logger = logging.getLogger(__name__)


class _DummyMessages:
    def stream(self, *args, **kwargs):  # pragma: no cover - simple placeholder
        raise ModuleNotFoundError(
            "anthropic SDK is not installed. Install 'anthropic' to enable streaming."
        )


class _DummyAnthropicClient:
    def __init__(self) -> None:  # pragma: no cover - simple placeholder
        self.messages = _DummyMessages()


class AnthropicProvider(Provider):
    def __init__(self, cfg: ProviderConfig):
        super().__init__(cfg)
        # Lazily provide a client so unit tests for helper methods don't require the SDK.
        self.client = (
            AsyncAnthropic(api_key=cfg.api_key)
            if AsyncAnthropic is not None
            else _DummyAnthropicClient()
        )

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
        async for chunk in self._completions_stream_with_retry(messages, tools):
            yield chunk

    async def _completions_stream_with_retry(
        self,
        original_messages: List[Dict[str, Any]],
        tools: Optional[List[ToolSpec]] = None,
        retry_count: int = 0,
    ) -> AsyncIterator[Dict[str, Any]]:
        try:
            # Convert messages to Anthropic format
            sys = self.cfg.system_prompt
            conv: List[Dict[str, Any]] = []
            for m in original_messages:
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

                # Intelligent error handling
                if api_error_handler.should_prune_context(e):
                    if retry_count < 2:  # Limit retries to prevent infinite loops
                        pruned_messages = context_manager.adaptive_prune_with_summary(
                            original_messages, str(e)
                        )
                        recovery_msg = api_error_handler.get_recovery_message(e)
                        yield {"type": "text", "delta": f"[RECOVERY] {recovery_msg}"}

                        # Retry with pruned context
                        async for chunk in self._completions_stream_with_retry(
                            pruned_messages, tools, retry_count + 1
                        ):
                            yield chunk
                        return

                # For rate limits and other retryable errors, use the error handler
                try:
                    analysis = api_error_handler.analyze_error(e)
                    if (
                        analysis.is_recoverable
                        and analysis.should_retry
                        and retry_count == 0
                    ):
                        recovery_msg = api_error_handler.get_recovery_message(e)
                        yield {"type": "text", "delta": f"[RECOVERY] {recovery_msg}"}

                        # Use the error handler's retry logic
                        async for chunk in api_error_handler.handle_error_with_retry(
                            e,
                            f"anthropic_stream_{id(original_messages)}",
                            self._completions_stream_with_retry,
                            original_messages,
                            tools,
                            retry_count + 1,
                        ):
                            yield chunk
                        return
                except Exception:
                    # If error handling fails, fall back to original error
                    pass

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
            content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc.get("arguments", {}),
            })
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
