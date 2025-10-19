from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, TypedDict


@dataclass
class ProviderConfig:
    model: str
    api_key: str
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    system_prompt: Optional[str] = None


class ToolSpec(TypedDict):
    """JSON schema-like tool definition for providers."""

    name: str
    description: str
    parameters: Dict[str, Any]


class Provider(ABC):
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    @abstractmethod
    async def list_tools_format(self, tools: List[ToolSpec]) -> Any:
        """Return provider-specific tool schema from generic ToolSpec list."""

    @abstractmethod
    def completions_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolSpec]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield assistant deltas and tool calls in a provider-agnostic way.
        Each yielded chunk is a dict like:
          {"type": "text", "delta": "..."}
          {"type": "tool_call", "id": "call_1", "name": "tool_name", "arguments": {...}}
        Stream ends when provider finishes a turn.
        """

    @abstractmethod
    def build_assistant_message(
        self, text: str, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Return a provider-formatted assistant message that includes text and tool call metadata for the next turn."""

    @abstractmethod
    def format_tool_result_message(
        self, tool_call_id: str, content: str
    ) -> Dict[str, Any]:
        """Return a provider-formatted message that conveys a tool result for a given tool call."""


class ProviderFactory:
    @staticmethod
    def create(name: str, cfg: ProviderConfig) -> Provider:
        lname = name.lower()
        if lname == "openai":
            from .openai_provider import OpenAIProvider

            return OpenAIProvider(cfg)
        if lname == "anthropic":
            from .anthropic_provider import AnthropicProvider

            return AnthropicProvider(cfg)
        if lname == "ollama":
            from .ollama_provider import OllamaProvider

            return OllamaProvider(cfg)
        raise ValueError(f"Unknown provider: {name}")
