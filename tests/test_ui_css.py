import asyncio
import os
import tempfile
from unittest.mock import patch

import pytest

from textual_cli_agent.ui.app import ChatApp
from textual_cli_agent.providers.base import Provider, ProviderConfig, ToolSpec
from textual.widgets import LoadingIndicator


class DummyProvider(Provider):
    async def list_tools_format(self, tools: list[ToolSpec]) -> list[ToolSpec]:
        return tools

    async def completions_stream(
        self, messages: list[dict], tools: list[ToolSpec] | None = None
    ):
        # No streaming required for CSS smoke test
        if False:
            yield {}
        return
        yield  # pragma: no cover

    def build_assistant_message(self, text: str, tool_calls: list[dict]) -> dict:
        return {"role": "assistant", "content": text}

    def format_tool_result_message(self, tool_call_id: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


@pytest.mark.asyncio
async def test_chat_app_css_parses() -> None:
    """Ensure ChatApp CSS loads without errors and mounts key widgets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            app = ChatApp(
                provider=DummyProvider(ProviderConfig(model="x", api_key="key")),
                mcp_manager=None,
            )
            async with app.run_test():
                await asyncio.sleep(0)
                indicator = app.query_one("#llm_indicator", LoadingIndicator)
                quit_button = app.query_one("#quit_button")
                header_quit = app.query_one("#header_quit_button")
                assert indicator is not None
                assert quit_button is not None
                assert header_quit is not None
                assert indicator.has_class("hidden")
                app._update_status(working=True)
                await asyncio.sleep(0)
                assert not indicator.has_class("hidden")
                app._update_status(working=False)
                await asyncio.sleep(0)
                assert indicator.has_class("hidden")
