from __future__ import annotations

import types
from typing import Any, AsyncIterator, Optional, List, cast
import pytest
from openai import AsyncOpenAI

from textual_cli_agent.providers.openai_provider import OpenAIProvider
from textual_cli_agent.providers.base import ProviderConfig


class FakeClient:
    def __init__(self) -> None:
        pass

    class choices0delta:
        def __init__(
            self,
            content: Optional[str] = None,
            tc: Optional[List[FakeClient.ChoiceDeltaToolCall]] = None,
        ) -> None:
            self.content = content
            self.tool_calls = tc

    class ChoiceDeltaToolCallFunction:
        def __init__(
            self, arguments: Optional[str] = None, name: Optional[str] = None
        ) -> None:
            self.arguments = arguments
            self.name = name

    class ChoiceDeltaToolCall:
        def __init__(
            self,
            index: int = 0,
            id: Optional[str] = None,
            function: Optional["FakeClient.ChoiceDeltaToolCallFunction"] = None,
        ) -> None:
            self.index = index
            self.id = id
            self.function = function

    class Choice:
        def __init__(self, delta: "FakeClient.choices0delta") -> None:
            self.delta = delta

    class Event:
        def __init__(self, delta: "FakeClient.choices0delta") -> None:
            self.choices = [FakeClient.Choice(delta)]

    async def chat_stream(self) -> AsyncIterator["FakeClient.Event"]:
        # Simulate chunked tool call arguments: '{', '"a":1', '}'
        tc1 = FakeClient.ChoiceDeltaToolCall(
            index=0,
            id="call_0",
            function=FakeClient.ChoiceDeltaToolCallFunction(arguments="{", name=None),
        )
        tc2 = FakeClient.ChoiceDeltaToolCall(
            index=0,
            id=None,
            function=FakeClient.ChoiceDeltaToolCallFunction(
                arguments='"a":1', name="glob_files"
            ),
        )
        tc3 = FakeClient.ChoiceDeltaToolCall(
            index=0,
            id=None,
            function=FakeClient.ChoiceDeltaToolCallFunction(arguments="}"),
        )
        for tc in (tc1, tc2, tc3):
            yield FakeClient.Event(FakeClient.choices0delta(content=None, tc=[tc]))


@pytest.mark.asyncio
async def test_chunked_tool_call_arguments_are_buffered(monkeypatch) -> None:
    prov = OpenAIProvider(ProviderConfig(model="gpt-4o", api_key="x"))

    async def fake_create(**kwargs: Any) -> AsyncIterator[FakeClient.Event]:
        async def agen(*args: Any, **kwargs: Any) -> AsyncIterator[FakeClient.Event]:
            async for e in FakeClient().chat_stream():
                yield e

        return agen()

    class Dummy:
        def __init__(self) -> None:
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=fake_create)
            )

    prov.client = cast(AsyncOpenAI, Dummy())

    # Collect tool_call events
    events: list[dict[str, Any]] = []
    async for chunk in prov.completions_stream(
        messages=[{"role": "user", "content": "hi"}], tools=[]
    ):
        events.append(chunk)
        if len(events) >= 1:
            break

    assert events[0]["type"] == "tool_call"
    assert events[0]["name"] == "glob_files"
    assert events[0]["arguments"] == {"a": 1}
