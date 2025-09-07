import pytest

try:
    from textual_cli_agent.providers.anthropic_provider import AnthropicProvider
except ModuleNotFoundError:
    pytest.skip(
        "anthropic provider optional dep not installed", allow_module_level=True
    )
from textual_cli_agent.providers.base import ProviderConfig


@pytest.mark.asyncio
async def test_anthropic_provider_build_assistant_message():
    prov = AnthropicProvider(
        ProviderConfig(model="claude-3-sonnet-20240229", api_key="test")
    )
    msg = prov.build_assistant_message(
        "hello", [{"id": "call_1", "name": "add", "arguments": {"a": 1, "b": 2}}]
    )
    assert msg["role"] == "assistant"
    assert len(msg["content"]) == 2
    assert msg["content"][0]["type"] == "text"
    assert msg["content"][0]["text"] == "hello"
    assert msg["content"][1]["type"] == "tool_use"
    assert msg["content"][1]["id"] == "call_1"
    assert msg["content"][1]["name"] == "add"
    assert msg["content"][1]["input"] == {"a": 1, "b": 2}


def test_anthropic_provider_format_tool_result_message():
    prov = AnthropicProvider(
        ProviderConfig(model="claude-3-sonnet-20240229", api_key="test")
    )
    msg = prov.format_tool_result_message("call_1", "result content")
    assert msg["role"] == "user"
    assert len(msg["content"]) == 1
    assert msg["content"][0]["type"] == "tool_result"
    assert msg["content"][0]["tool_use_id"] == "call_1"
    assert msg["content"][0]["content"] == "result content"


@pytest.mark.asyncio
async def test_anthropic_provider_list_tools_format():
    prov = AnthropicProvider(
        ProviderConfig(model="claude-3-sonnet-20240229", api_key="test")
    )
    tools = [
        {
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {"type": "object", "properties": {"arg": {"type": "string"}}},
        }
    ]
    anthropic_tools = await prov.list_tools_format(tools)
    assert len(anthropic_tools) == 1
    tool = anthropic_tools[0]
    assert tool["name"] == "test_tool"
    assert tool["description"] == "A test tool"
    assert "input_schema" in tool
    assert tool["input_schema"]["type"] == "object"
