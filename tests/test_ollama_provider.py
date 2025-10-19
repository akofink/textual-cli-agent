import pytest

from textual_cli_agent.providers.base import ProviderConfig, ProviderFactory
from textual_cli_agent.providers.ollama_provider import OllamaProvider


def test_provider_factory_creates_ollama():
    cfg = ProviderConfig(model="llama3", api_key="")
    provider = ProviderFactory.create("ollama", cfg)
    assert isinstance(provider, OllamaProvider)


@pytest.mark.asyncio
async def test_ollama_provider_build_assistant_message():
    provider = OllamaProvider(ProviderConfig(model="llama3", api_key=""))
    tool_calls = [
        {"id": "call_1", "name": "add", "arguments": {"a": 1, "b": 2}},
    ]
    msg = provider.build_assistant_message("hello", tool_calls)

    assert msg["role"] == "assistant"
    assert msg["content"] == "hello"
    assert "tool_calls" in msg
    tool_call = msg["tool_calls"][0]
    assert tool_call["id"] == "call_1"
    assert tool_call["function"]["name"] == "add"
    assert tool_call["function"]["arguments"] == '{"a": 1, "b": 2}'


@pytest.mark.asyncio
async def test_ollama_provider_parses_stream(monkeypatch):
    provider = OllamaProvider(ProviderConfig(model="llama3", api_key=""))

    events = [
        {"message": {"role": "assistant", "content": "Hello"}},
        {
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "add",
                            "arguments": '{"a": 3, "b": 5}',
                        },
                    }
                ],
            }
        },
        {"message": {"role": "assistant", "content": " world!"}},
        {"done": True},
    ]

    async def fake_stream(self, payload):
        assert payload["model"] == "llama3"
        assert payload["stream"] is True
        for event in events:
            yield event

    monkeypatch.setattr(OllamaProvider, "_stream_chat", fake_stream, raising=True)

    messages = [{"role": "user", "content": "Say hi"}]
    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0]["type"] == "text"
    assert chunks[0]["delta"] == "Hello"

    tool_chunk = chunks[1]
    assert tool_chunk["type"] == "tool_call"
    assert tool_chunk["id"] == "call_1"
    assert tool_chunk["name"] == "add"
    assert tool_chunk["arguments"] == {"a": 3, "b": 5}

    assert chunks[2]["type"] == "text"
    assert chunks[2]["delta"] == " world!"

    # Tool result message should include function name
    tool_message = provider.format_tool_result_message("call_1", '{"result": 8}')
    assert tool_message["name"] == "add"
    assert tool_message["tool_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_ollama_provider_http_error(monkeypatch):
    provider = OllamaProvider(ProviderConfig(model="llama3", api_key=""))

    async def failing_stream(self, payload):
        raise RuntimeError("Ollama HTTP error 400: tool result malformed")
        yield  # pragma: no cover - keep async generator type

    monkeypatch.setattr(OllamaProvider, "_stream_chat", failing_stream, raising=True)

    messages = [{"role": "user", "content": "Hi"}]
    chunks = []
    async for chunk in provider.completions_stream(messages):
        chunks.append(chunk)

    assert any(
        c.get("type") == "text" and "tool result malformed" in c.get("delta", "")
        for c in chunks
    )
