from __future__ import annotations

import types

import pytest

from textual_cli_agent.providers.base import Provider, ProviderConfig, ProviderFactory


class _StubProvider(Provider):
    async def list_tools_format(self, tools):
        return tools

    def completions_stream(self, messages, tools=None):
        async def _gen():
            if False:
                yield {}

        return _gen()

    def build_assistant_message(self, text, tool_calls):
        return {"role": "assistant", "content": text}

    def format_tool_result_message(self, tool_call_id, content):
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _install_stub(module_name: str, class_name: str) -> None:
    module = types.ModuleType(module_name)
    setattr(module, class_name, _StubProvider)
    import sys

    sys.modules[module_name] = module


def test_provider_factory_creates_known_providers(monkeypatch):
    _install_stub("textual_cli_agent.providers.openai_provider", "OpenAIProvider")
    _install_stub("textual_cli_agent.providers.anthropic_provider", "AnthropicProvider")
    _install_stub("textual_cli_agent.providers.ollama_provider", "OllamaProvider")

    cfg = ProviderConfig(model="test", api_key="key")
    assert isinstance(ProviderFactory.create("openai", cfg), _StubProvider)
    assert isinstance(ProviderFactory.create("anthropic", cfg), _StubProvider)
    assert isinstance(ProviderFactory.create("ollama", cfg), _StubProvider)


def test_provider_factory_unknown():
    cfg = ProviderConfig(model="test", api_key="key")
    with pytest.raises(ValueError):
        ProviderFactory.create("unknown", cfg)
