import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest  # type: ignore[import-not-found]

from textual_cli_agent.ui.app import ChatApp  # type: ignore[import-not-found]
from textual_cli_agent.providers.base import Provider, ProviderConfig, ToolSpec  # type: ignore[import-not-found]


class FakeProvider(Provider):  # type: ignore[misc]
    async def list_tools_format(self, tools: List[ToolSpec]) -> Any:
        return []

    async def completions_stream(
        self, messages: List[Dict[str, Any]], tools: Optional[List[ToolSpec]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        if False:
            yield {}
        return
        yield  # pragma: no cover

    def build_assistant_message(
        self, text: str, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return {"role": "assistant", "content": text}

    def format_tool_result_message(
        self, tool_call_id: str, content: str
    ) -> Dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


@pytest.mark.asyncio  # type: ignore[misc]
async def test_ctrl_c_quits() -> None:
    app = ChatApp(
        provider=FakeProvider(ProviderConfig(model="x", api_key="x")), mcp_manager=None
    )
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        # allow the app to process the event loop turn
        await asyncio.sleep(0)
        assert app.is_running is False


@pytest.mark.asyncio  # type: ignore[misc]
async def test_ctrl_d_quits() -> None:
    app = ChatApp(
        provider=FakeProvider(ProviderConfig(model="x", api_key="x")), mcp_manager=None
    )
    async with app.run_test() as pilot:
        await pilot.press("ctrl+d")
        await asyncio.sleep(0)
        assert app.is_running is False
