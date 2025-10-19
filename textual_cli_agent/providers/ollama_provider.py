from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Set

import httpx

from .base import Provider, ProviderConfig, ToolSpec
from ..context_manager import context_manager
from ..error_handler import api_error_handler

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaProvider(Provider):
    def __init__(self, cfg: ProviderConfig):
        super().__init__(cfg)
        self.base_url = (cfg.base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        self._tool_name_map: Dict[str, str] = {}

    async def list_tools_format(self, tools: List[ToolSpec]) -> Any:
        # Ollama follows the OpenAI-style JSON schema for tool definitions
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
        async for chunk in self._completions_stream_with_retry(messages, tools):
            yield chunk

    async def _completions_stream_with_retry(
        self,
        original_messages: List[Dict[str, Any]],
        tools: Optional[List[ToolSpec]] = None,
        retry_count: int = 0,
    ) -> AsyncIterator[Dict[str, Any]]:
        try:
            tool_schema = await self.list_tools_format(tools or []) if tools else None

            msgs = [dict(m) for m in original_messages if isinstance(m, dict)]

            if self.cfg.system_prompt and not any(
                m.get("role") == "system" for m in msgs
            ):
                msgs = [{"role": "system", "content": self.cfg.system_prompt}] + msgs

            payload: Dict[str, Any] = {
                "model": self.cfg.model,
                "messages": msgs,
                "stream": True,
            }
            if tool_schema:
                payload["tools"] = tool_schema
            if self.cfg.temperature is not None:
                payload["options"] = {"temperature": self.cfg.temperature}

            emitted_tool_ids: Set[str] = set()

            async for event in self._stream_chat(payload):
                try:
                    # Ollama errors may be returned inline
                    if event.get("error"):
                        err_msg = event.get("error")
                        yield {"type": "text", "delta": f"[ERROR] {err_msg}"}
                        continue

                    message = event.get("message") or {}

                    # Tool calls (emitted once per unique id)
                    tool_calls: Iterable[Dict[str, Any]] = (
                        message.get("tool_calls", []) or []
                    )
                    for idx, tc in enumerate(tool_calls):
                        call_id = str(tc.get("id") or f"call_{idx}")
                        if call_id in emitted_tool_ids:
                            continue
                        emitted_tool_ids.add(call_id)

                        func = tc.get("function", {})
                        name = func.get("name") or tc.get("name") or f"tool_{idx}"
                        raw_args = func.get("arguments")
                        try:
                            if isinstance(raw_args, str):
                                args = json.loads(raw_args) if raw_args.strip() else {}
                            elif isinstance(raw_args, dict):
                                args = raw_args
                            else:
                                args = {}
                        except json.JSONDecodeError as je:
                            logger.debug(f"Ollama tool call JSON error: {je}")
                            args = {}

                        yield {
                            "type": "tool_call",
                            "id": call_id,
                            "name": name,
                            "arguments": args,
                        }
                        self._tool_name_map[call_id] = name

                    content = message.get("content")
                    if isinstance(content, str) and content:
                        yield {"type": "text", "delta": content}
                except Exception as stream_err:
                    logger.error(
                        f"Error processing Ollama stream event {event}: {stream_err}"
                    )
                    yield {
                        "type": "text",
                        "delta": f"[ERROR] Stream processing failed: {stream_err}",
                    }
        except Exception as e:
            logger.error(f"Ollama API call failed: {e}")

            if api_error_handler.should_prune_context(e):
                if retry_count < 2:
                    pruned_messages = context_manager.adaptive_prune_with_summary(
                        original_messages, str(e)
                    )
                    recovery_msg = api_error_handler.get_recovery_message(e)
                    yield {"type": "text", "delta": f"[RECOVERY] {recovery_msg}"}

                    async for chunk in self._completions_stream_with_retry(
                        pruned_messages, tools, retry_count + 1
                    ):
                        yield chunk
                    return

            try:
                analysis = api_error_handler.analyze_error(e)
                if (
                    analysis.is_recoverable
                    and analysis.should_retry
                    and retry_count == 0
                ):
                    recovery_msg = api_error_handler.get_recovery_message(e)
                    if recovery_msg:
                        yield {"type": "text", "delta": f"[RECOVERY] {recovery_msg}"}

                    async for chunk in api_error_handler.handle_error_with_retry(
                        e,
                        f"ollama_stream_{id(original_messages)}",
                        self._completions_stream_with_retry,
                        original_messages,
                        tools,
                        retry_count + 1,
                    ):
                        yield chunk
                    return
            except Exception:
                pass

            yield {"type": "text", "delta": f"[ERROR] API call failed: {str(e)}"}

    async def _stream_chat(
        self, payload: Dict[str, Any]
    ) -> AsyncIterator[Dict[str, Any]]:
        url = f"{self.base_url}/api/chat"
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code >= 400:
                        body_bytes = await response.aread()
                        response_detail: Optional[str] = None
                        if body_bytes:
                            try:
                                decoded = body_bytes.decode("utf-8")
                                detail_json = json.loads(decoded)
                                if isinstance(detail_json, dict):
                                    response_detail = detail_json.get(
                                        "error"
                                    ) or detail_json.get("message")
                                    if response_detail is None:
                                        response_detail = json.dumps(detail_json)
                                else:
                                    response_detail = str(detail_json)
                            except Exception:
                                response_detail = body_bytes.decode(
                                    "utf-8", errors="ignore"
                                ).strip()
                        error_msg = (
                            f"Ollama HTTP error {response.status_code}: {response_detail}"
                            if response_detail
                            else f"Ollama HTTP error {response.status_code}"
                        )
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            logger.debug(f"Skipping non-JSON Ollama chunk: {line!r}")
                            continue
            except httpx.HTTPStatusError as http_err:
                status = http_err.response.status_code
                # Ensure the streaming response body is fully read before accessing it.
                try:
                    await http_err.response.aread()
                except Exception:
                    pass
                error_detail: Optional[str] = None
                try:
                    payload = http_err.response.json()
                    if isinstance(payload, dict):
                        error_detail = payload.get("error") or payload.get("message")
                        if error_detail is None:
                            error_detail = json.dumps(payload)
                    else:
                        error_detail = str(payload)
                except ValueError:
                    try:
                        error_detail = http_err.response.text.strip() or None
                    except Exception:
                        error_detail = None

                error_msg = (
                    f"Ollama HTTP error {status}: {error_detail}"
                    if error_detail
                    else f"Ollama HTTP error {status}"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg) from http_err
            except httpx.HTTPError as http_err:
                resp = getattr(http_err, "response", None)
                if resp is not None:
                    try:
                        await resp.aread()
                    except Exception:
                        pass
                logger.error(f"Ollama HTTP error: {http_err}")
                raise

    def build_assistant_message(
        self, text: str, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        message: Dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            formatted_calls = []
            for call in tool_calls:
                args = call.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        # Leave as-is; Ollama expects object and will report error if invalid.
                        logger.debug(f"Ollama tool args were string: {args!r}")
                formatted_calls.append({
                    "id": call.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": args,
                    },
                })
            message["tool_calls"] = formatted_calls
        return message

    def format_tool_result_message(
        self, tool_call_id: str, content: str
    ) -> Dict[str, Any]:
        tool_name = self._tool_name_map.pop(tool_call_id, "")
        message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }
        if tool_name:
            message["name"] = tool_name
        return message
