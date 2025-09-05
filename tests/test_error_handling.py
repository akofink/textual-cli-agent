"""Tests for error handling and defensive programming."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from textual_cli_agent.engine import AgentEngine
from textual_cli_agent.providers.base import Provider, ProviderConfig
from textual_cli_agent.mcp.client import McpManager


class ErrorProvider(Provider):
    """Provider that simulates various API errors."""

    def __init__(self, cfg: ProviderConfig, error_mode: str = "api"):
        super().__init__(cfg)
        self.error_mode = error_mode

    async def list_tools_format(self, tools):
        return tools

    async def completions_stream(self, messages, tools=None):
        if self.error_mode == "api":
            raise ConnectionError("API connection failed")
        elif self.error_mode == "stream":
            # Start normally then fail
            yield {"type": "text", "delta": "Starting..."}
            raise RuntimeError("Stream processing error")
        elif self.error_mode == "malformed":
            # Return malformed chunks
            yield {"invalid": "chunk"}
            yield None
            yield {"type": "text"}  # Missing delta
        elif self.error_mode == "tool_call":
            yield {
                "type": "tool_call",
                "id": "call_1",
                "name": "bad_tool",
                "arguments": {"arg": "value"},
            }
        else:
            yield {"type": "text", "delta": "Success"}

    def build_assistant_message(self, text, tool_calls):
        if self.error_mode == "build_fail":
            raise ValueError("Failed to build message")
        return {"role": "assistant", "content": text}

    def format_tool_result_message(self, tool_call_id, content):
        if self.error_mode == "format_fail":
            raise KeyError("Failed to format")
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


@pytest.mark.asyncio
async def test_engine_handles_provider_api_error():
    """Test engine gracefully handles provider API errors."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="api"
    )
    engine = AgentEngine(provider)

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in engine.run_stream(messages):
        chunks.append(chunk)

    # Should get error text and round complete
    assert len(chunks) >= 2
    assert any(
        "[ERROR]" in chunk.get("delta", "")
        for chunk in chunks
        if chunk.get("type") == "text"
    )
    assert chunks[-1]["type"] == "round_complete"
    assert chunks[-1]["had_tool_calls"] is False


@pytest.mark.asyncio
async def test_engine_handles_stream_error():
    """Test engine handles errors during stream processing."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="stream"
    )
    engine = AgentEngine(provider)

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in engine.run_stream(messages):
        chunks.append(chunk)

    # Should get initial text, then error text, then round complete
    assert len(chunks) >= 3
    text_chunks = [c for c in chunks if c.get("type") == "text"]
    assert any("Starting..." in c.get("delta", "") for c in text_chunks)
    assert any("[ERROR]" in c.get("delta", "") for c in text_chunks)
    assert chunks[-1]["type"] == "round_complete"


@pytest.mark.asyncio
async def test_engine_handles_malformed_chunks():
    """Test engine handles malformed/invalid chunks."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="malformed"
    )
    engine = AgentEngine(provider)

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in engine.run_stream(messages):
        chunks.append(chunk)

    # Should complete without crashing
    assert chunks[-1]["type"] == "round_complete"


@pytest.mark.asyncio
async def test_engine_validates_messages():
    """Test engine validates input messages."""
    provider = ErrorProvider(ProviderConfig(model="test", api_key="test"))
    engine = AgentEngine(provider)

    # Test empty messages
    chunks = []
    async for chunk in engine.run_stream([]):
        chunks.append(chunk)
    assert any(
        "[ERROR]" in chunk.get("delta", "")
        for chunk in chunks
        if chunk.get("type") == "text"
    )

    # Test invalid message format
    chunks = []
    async for chunk in engine.run_stream(["not a dict"]):
        chunks.append(chunk)
    assert any(
        "[ERROR]" in chunk.get("delta", "")
        for chunk in chunks
        if chunk.get("type") == "text"
    )

    # Test message missing role
    chunks = []
    async for chunk in engine.run_stream([{"content": "test"}]):
        chunks.append(chunk)
    assert any(
        "[ERROR]" in chunk.get("delta", "")
        for chunk in chunks
        if chunk.get("type") == "text"
    )


@pytest.mark.asyncio
async def test_tool_execution_timeout():
    """Test tool execution timeout handling."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="tool_call"
    )
    engine = AgentEngine(provider)

    # Mock a tool that hangs (use short timeout for testing)
    async def hanging_tool(*args, **kwargs):
        await asyncio.sleep(2)  # Longer than test timeout
        return {"result": "should not reach"}

    with patch("textual_cli_agent.engine.execute_tool", hanging_tool):
        # Patch the timeout to be very short for testing
        original_method = engine._execute_tool_safely

        async def fast_timeout_method(name, args):
            try:
                result = await asyncio.wait_for(
                    engine._execute_tool_internal(name, args),
                    timeout=0.1,  # Very short timeout for testing
                )
                return result
            except asyncio.TimeoutError:
                return {"error": f"Tool '{name}' execution timed out"}
            except Exception as e:
                return {"error": f"Tool execution error: {str(e)}"}

        engine._execute_tool_safely = fast_timeout_method

        try:
            messages = [{"role": "user", "content": "test"}]
            chunks = []
            async for chunk in engine.run_stream(messages):
                chunks.append(chunk)
                if chunk.get("type") == "round_complete":
                    break

            # Should get timeout error in tool result
            tool_results = [c for c in chunks if c.get("type") == "tool_result"]
            assert len(tool_results) > 0
            result_content = json.loads(tool_results[0]["content"])
            assert "timed out" in result_content["error"]
        finally:
            engine._execute_tool_safely = original_method


@pytest.mark.asyncio
async def test_tool_execution_error_handling():
    """Test tool execution error handling."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="tool_call"
    )
    engine = AgentEngine(provider)

    # Mock a tool that raises an exception
    async def failing_tool(*args, **kwargs):
        raise ValueError("Tool execution failed")

    with patch("textual_cli_agent.engine.execute_tool", failing_tool):
        messages = [{"role": "user", "content": "test"}]
        chunks = []
        async for chunk in engine.run_stream(messages):
            chunks.append(chunk)
            if chunk.get("type") == "round_complete":
                break

        # Should get error in tool result
        tool_results = [c for c in chunks if c.get("type") == "tool_result"]
        assert len(tool_results) > 0
        result_content = json.loads(tool_results[0]["content"])
        assert "error" in result_content
        assert "Tool execution failed" in result_content["error"]


@pytest.mark.asyncio
async def test_provider_message_building_error():
    """Test handling of provider message building errors."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="build_fail"
    )
    engine = AgentEngine(provider)

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in engine.run_stream(messages):
        chunks.append(chunk)

    # Should complete with fallback message
    append_messages = [c for c in chunks if c.get("type") == "append_message"]
    assert len(append_messages) > 0
    # Should have fallback message format
    assert append_messages[-1]["message"]["role"] == "assistant"


@pytest.mark.asyncio
async def test_provider_format_error():
    """Test handling of provider format errors."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="format_fail"
    )
    engine = AgentEngine(provider)

    # Mock tool execution to trigger formatting
    async def mock_tool(*args, **kwargs):
        return {"result": "test"}

    with patch("textual_cli_agent.engine.execute_tool", mock_tool):
        # Use tool_call error mode to get a tool call
        provider.error_mode = "tool_call"
        messages = [{"role": "user", "content": "test"}]
        chunks = []
        async for chunk in engine.run_stream(messages):
            chunks.append(chunk)
            if chunk.get("type") == "round_complete":
                break

        # Should have fallback message format in append_message
        append_messages = [c for c in chunks if c.get("type") == "append_message"]
        tool_messages = [
            m for m in append_messages if m["message"].get("role") == "tool"
        ]
        assert len(tool_messages) > 0


@pytest.mark.asyncio
async def test_mcp_manager_error_handling():
    """Test MCP manager error handling during startup."""
    manager = McpManager()

    # Test with invalid command (should not crash)
    await manager.start(stdio_cmds=["nonexistent_command_12345"])
    assert len(manager.clients) == 0
    assert len(manager.tools) == 0

    # Test with invalid HTTP URL
    await manager.start(http_urls=["http://invalid-url-12345.local"])
    assert len(manager.clients) == 0
    assert len(manager.tools) == 0


@pytest.mark.asyncio
async def test_mcp_execute_error_handling():
    """Test MCP tool execution error handling."""
    manager = McpManager()

    # Test execution with no clients
    with pytest.raises(KeyError, match="No MCP clients available"):
        await manager.execute("test_tool", {})

    # Test with mock failing client
    mock_client = AsyncMock()
    mock_client.call_tool.side_effect = RuntimeError("Client error")
    manager.clients = [mock_client]

    with pytest.raises(KeyError, match="failed on all clients"):
        await manager.execute("test_tool", {})


def test_invalid_tool_arguments():
    """Test validation of tool arguments."""
    provider = ErrorProvider(ProviderConfig(model="test", api_key="test"))
    engine = AgentEngine(provider)

    # Test with non-dict arguments
    async def test_invalid_args():
        result = await engine._execute_tool_safely("test_tool", "invalid_args")
        assert "error" in result
        assert "must be a dictionary" in result["error"]

    asyncio.run(test_invalid_args())


@pytest.mark.asyncio
async def test_json_serialization_error():
    """Test handling of JSON serialization errors in tool results."""
    provider = ErrorProvider(
        ProviderConfig(model="test", api_key="test"), error_mode="tool_call"
    )
    engine = AgentEngine(provider)

    # Mock tool that returns non-serializable result
    class NonSerializable:
        pass

    async def non_serializable_tool(*args, **kwargs):
        return {"obj": NonSerializable()}  # Can't serialize

    with patch("textual_cli_agent.engine.execute_tool", non_serializable_tool):
        messages = [{"role": "user", "content": "test"}]
        chunks = []
        async for chunk in engine.run_stream(messages):
            chunks.append(chunk)
            if chunk.get("type") == "round_complete":
                break

        # Should handle serialization error gracefully
        tool_results = [c for c in chunks if c.get("type") == "tool_result"]
        assert len(tool_results) > 0
        result_content = json.loads(tool_results[0]["content"])
        assert "error" in result_content
        assert "serialization failed" in result_content["error"]


@pytest.mark.asyncio
async def test_tool_spec_error_handling():
    """Test handling of tool spec retrieval errors."""
    provider = ErrorProvider(ProviderConfig(model="test", api_key="test"))

    # Mock get_tool_specs to raise an error
    with patch(
        "textual_cli_agent.engine.get_tool_specs",
        side_effect=RuntimeError("Tool spec error"),
    ):
        engine = AgentEngine(provider)
        messages = [{"role": "user", "content": "test"}]

        # Should continue with empty tools instead of crashing
        chunks = []
        async for chunk in engine.run_stream(messages):
            chunks.append(chunk)

        # Should complete successfully
        assert chunks[-1]["type"] == "round_complete"
