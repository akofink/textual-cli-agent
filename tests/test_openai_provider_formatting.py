import pytest

from textual_cli_agent.providers.openai_provider import OpenAIProvider
from textual_cli_agent.providers.base import ProviderConfig


@pytest.mark.asyncio
async def test_openai_provider_build_assistant_message():
    prov = OpenAIProvider(ProviderConfig(model="gpt-4o", api_key="test"))
    msg = prov.build_assistant_message("hello", [
        {"id": "call_1", "name": "add", "arguments": {"a": 1, "b": 2}}
    ])
    assert msg["role"] == "assistant"
    assert msg["content"] == "hello"
    assert "tool_calls" in msg
    tc = msg["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["function"]["name"] == "add"
