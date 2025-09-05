from unittest.mock import MagicMock

from textual_cli_agent.engine import AgentEngine
from textual_cli_agent.providers.base import Provider, ProviderConfig


class MockProvider(Provider):
    def __init__(self, cfg: ProviderConfig):
        super().__init__(cfg)

    async def list_tools_format(self, tools):
        return tools

    async def completions_stream(self, messages, tools=None):
        # Simple mock that yields a text chunk
        yield {"type": "text", "delta": "test response"}

    def build_assistant_message(self, text, tool_calls):
        return {"role": "assistant", "content": text, "tool_calls": tool_calls}

    def format_tool_result_message(self, tool_call_id, content):
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def test_agent_engine_init():
    provider = MockProvider(ProviderConfig(model="test", api_key="test"))
    mcp_manager = None
    engine = AgentEngine(provider, mcp_manager)
    assert engine.provider == provider
    assert engine.mcp_manager == mcp_manager


def test_combined_tool_specs():
    provider = MockProvider(ProviderConfig(model="test", api_key="test"))
    mcp_manager = None
    engine = AgentEngine(provider, mcp_manager)
    specs = engine._combined_tool_specs()
    # Should return the built-in tool specs
    assert isinstance(specs, list)
    assert len(specs) > 0  # We have some built-in tools


def test_combined_tool_specs_with_mcp():
    provider = MockProvider(ProviderConfig(model="test", api_key="test"))
    mcp_manager = MagicMock()
    mcp_manager.tool_specs.return_value = [
        {"name": "mcp_tool", "description": "test", "parameters": {}}
    ]
    engine = AgentEngine(provider, mcp_manager)
    specs = engine._combined_tool_specs()
    # Should include both built-in and MCP tools
    assert isinstance(specs, list)
    assert any(spec["name"] == "mcp_tool" for spec in specs)
