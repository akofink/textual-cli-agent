import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from typing import Any

import pytest  # type: ignore[import-not-found]

from textual_cli_agent.ui.app import ChatApp  # type: ignore[import-not-found]
from textual_cli_agent.providers.base import Provider, ProviderConfig, ToolSpec  # type: ignore[import-not-found]


class FakeProvider(Provider):  # type: ignore[misc]
    async def list_tools_format(self, tools: list[ToolSpec]) -> Any:
        return []

    async def completions_stream(
        self, messages: list[dict], tools: list[ToolSpec] | None = None
    ) -> Any:
        if False:
            yield {}
        return
        yield  # pragma: no cover

    def build_assistant_message(self, text: str, tool_calls: list[dict]) -> dict:
        return {"role": "assistant", "content": text}

    def format_tool_result_message(self, tool_call_id: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


@pytest.mark.asyncio  # type: ignore[misc]
async def test_theme_set_from_palette_persists() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            app = ChatApp(
                provider=FakeProvider(ProviderConfig(model="x", api_key="x")),
                mcp_manager=None,
            )
            async with app.run_test():
                # Simulate command palette invoking set_theme
                app.action_set_theme("solarized-light")
                await asyncio.sleep(0)

            cfg_path = Path(tmpdir) / "textual-cli-agent" / "config.json"
            assert cfg_path.exists()
            data = json.loads(cfg_path.read_text())
            assert data.get("theme") == app.theme

            # New app should apply saved theme
            app2 = ChatApp(
                provider=FakeProvider(ProviderConfig(model="x", api_key="x")),
                mcp_manager=None,
            )
            assert app2.theme == "solarized-light"
