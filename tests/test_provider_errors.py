"""Tests for provider-specific error handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from textual_cli_agent.providers.openai_provider import OpenAIProvider
from textual_cli_agent.providers.anthropic_provider import AnthropicProvider
from textual_cli_agent.providers.base import ProviderConfig


@pytest.mark.asyncio
async def test_openai_provider_api_error():
    """Test OpenAI provider handles API errors gracefully."""
    config = ProviderConfig(model="gpt-4", api_key="test")
    provider = OpenAIProvider(config)

    # Mock the client to raise an API error
    provider.client.chat.completions.create = AsyncMock(
        side_effect=Exception("API rate limit exceeded")
    )

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should get error message
    assert len(chunks) >= 1
    assert chunks[0]["type"] == "text"
    assert "[ERROR]" in chunks[0]["delta"]
    assert "API rate limit exceeded" in chunks[0]["delta"]


@pytest.mark.asyncio
async def test_openai_provider_stream_error():
    """Test OpenAI provider handles streaming errors."""
    config = ProviderConfig(model="gpt-4", api_key="test")
    provider = OpenAIProvider(config)

    # Mock stream that yields some data then fails
    async def failing_stream():
        # Yield a valid event first
        event = MagicMock()
        event.choices = [MagicMock()]
        event.choices[0].delta = MagicMock()
        event.choices[0].delta.content = "Hello"
        yield event

        # Then raise an error
        raise ConnectionError("Connection lost")

    mock_response = MagicMock()
    mock_response.__aiter__ = lambda self: failing_stream()

    provider.client.chat.completions.create = AsyncMock(return_value=mock_response)

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should get initial text then error
    assert len(chunks) >= 2
    assert chunks[0]["type"] == "text"
    assert chunks[0]["delta"] == "Hello"

    error_chunks = [
        c for c in chunks if c.get("type") == "text" and "[ERROR]" in c.get("delta", "")
    ]
    assert len(error_chunks) > 0


@pytest.mark.asyncio
async def test_openai_provider_malformed_events():
    """Test OpenAI provider handles malformed events."""
    config = ProviderConfig(model="gpt-4", api_key="test")
    provider = OpenAIProvider(config)

    # Mock stream that yields malformed events
    async def malformed_stream():
        # No choices
        yield MagicMock(choices=None)

        # No delta
        event = MagicMock()
        event.choices = [MagicMock(delta=None)]
        yield event

        # Valid event
        event = MagicMock()
        event.choices = [MagicMock()]
        event.choices[0].delta = MagicMock()
        event.choices[0].delta.content = "Valid"
        yield event

    mock_response = MagicMock()
    mock_response.__aiter__ = lambda self: malformed_stream()

    provider.client.chat.completions.create = AsyncMock(return_value=mock_response)

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should only get the valid chunk
    assert len(chunks) == 1
    assert chunks[0]["type"] == "text"
    assert chunks[0]["delta"] == "Valid"


@pytest.mark.asyncio
async def test_openai_provider_handles_json_errors():
    """Test that OpenAI provider gracefully handles JSON parsing errors."""
    config = ProviderConfig(model="gpt-4", api_key="test")
    provider = OpenAIProvider(config)

    # Test that provider doesn't crash when processing invalid JSON
    # This tests the error handling path without complex mocking
    messages = [{"role": "user", "content": "test"}]

    # Mock client to raise a JSON-related error
    provider.client.chat.completions.create = AsyncMock(
        side_effect=ValueError("Invalid JSON response from API")
    )

    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should get error message instead of crashing
    assert len(chunks) >= 1
    assert chunks[0]["type"] == "text"
    assert "[ERROR]" in chunks[0]["delta"]


@pytest.mark.asyncio
async def test_anthropic_provider_api_error():
    """Test Anthropic provider handles API errors gracefully."""
    config = ProviderConfig(model="claude-3-sonnet-20240229", api_key="test")
    provider = AnthropicProvider(config)

    # Mock the client stream method to raise an error
    provider.client.messages.stream = MagicMock(
        side_effect=Exception("Anthropic API error")
    )

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should get error message
    assert len(chunks) >= 1
    assert chunks[0]["type"] == "text"
    assert "[ERROR]" in chunks[0]["delta"]
    assert "API call failed" in chunks[0]["delta"]


@pytest.mark.asyncio
async def test_anthropic_provider_invalid_messages():
    """Test Anthropic provider handles invalid messages."""
    config = ProviderConfig(model="claude-3-sonnet-20240229", api_key="test")
    provider = AnthropicProvider(config)

    # Messages with missing content
    messages = [
        {"role": "user"},  # Missing content
        {"role": "user", "content": None},  # None content
        {"role": "user", "content": "valid"},  # Valid message
    ]

    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should process only the valid message (but may fail on API call which is fine)
    # The important thing is it doesn't crash


@pytest.mark.asyncio
async def test_anthropic_provider_handles_stream_errors():
    """Test that Anthropic provider gracefully handles stream processing errors."""
    config = ProviderConfig(model="claude-3-sonnet-20240229", api_key="test")
    provider = AnthropicProvider(config)

    # Mock the client stream method to raise an error during streaming
    provider.client.messages.stream = MagicMock(
        side_effect=RuntimeError("Stream processing failed")
    )

    messages = [{"role": "user", "content": "test"}]
    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should get error message instead of crashing
    assert len(chunks) >= 1
    assert chunks[0]["type"] == "text"
    assert "[ERROR]" in chunks[0]["delta"]


@pytest.mark.asyncio
async def test_anthropic_provider_no_valid_messages():
    """Test Anthropic provider handles case with no valid messages."""
    config = ProviderConfig(model="claude-3-sonnet-20240229", api_key="test")
    provider = AnthropicProvider(config)

    # All invalid messages
    messages = [
        {
            "role": "system",
            "content": "system prompt",
        },  # System messages are filtered out
        {"role": "user"},  # Missing content
        {"content": "no role"},  # Missing role
    ]

    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    # Should get error - either about no valid messages OR API error (both are valid)
    assert len(chunks) >= 1
    assert chunks[0]["type"] == "text"
    assert "[ERROR]" in chunks[0]["delta"]
    # Could be either error message
    assert (
        "No valid messages" in chunks[0]["delta"]
        or "API call failed" in chunks[0]["delta"]
    )


def test_provider_config_validation():
    """Test provider configuration edge cases."""
    # Test with minimal config
    config = ProviderConfig(model="test", api_key="test")
    assert config.model == "test"
    assert config.api_key == "test"
    assert config.base_url is None
    assert config.temperature is None
    assert config.system_prompt is None

    # Test with all fields
    config = ProviderConfig(
        model="test",
        api_key="test",
        base_url="https://api.test.com",
        temperature=0.7,
        system_prompt="Test prompt",
    )
    assert config.base_url == "https://api.test.com"
    assert config.temperature == 0.7
    assert config.system_prompt == "Test prompt"
