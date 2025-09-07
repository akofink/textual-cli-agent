import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest  # type: ignore[import-not-found]

from textual_cli_agent.ui.app import ChatApp  # type: ignore[import-not-found]
from textual_cli_agent.providers.base import Provider, ProviderConfig, ToolSpec  # type: ignore[import-not-found]


class FakeProvider(Provider):  # type: ignore[misc]
    async def list_tools_format(self, tools: list[ToolSpec]) -> any:
        return []

    async def completions_stream(
        self, messages: list[dict], tools: list[ToolSpec] | None = None
    ) -> any:
        if False:
            yield {}
        return
        yield  # pragma: no cover

    def build_assistant_message(self, text: str, tool_calls: list[dict]) -> dict:
        return {"role": "assistant", "content": text}

    def format_tool_result_message(self, tool_call_id: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


@pytest.mark.asyncio  # type: ignore[misc]
async def test_theme_toggle_persists_to_xdg_config() -> None:
    # Use a temp XDG config home to avoid touching real filesystem
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            app = ChatApp(
                provider=FakeProvider(ProviderConfig(model="x", api_key="x")),
                mcp_manager=None,
            )
            # Run a minimal test session so the app is initialized
            async with app.run_test():
                # Toggle dark mode
                app.action_toggle_dark()
                await asyncio.sleep(0)

            # Verify config file was written with theme preference
            config_path = Path(tmpdir) / "textual-cli-agent" / "config.json"
            assert config_path.exists(), f"Expected config at {config_path}"
            data = json.loads(config_path.read_text())
            assert isinstance(data.get("theme"), str)

            # Start a new app instance and confirm it applies the saved theme by name
            app2 = ChatApp(
                provider=FakeProvider(ProviderConfig(model="x", api_key="x")),
                mcp_manager=None,
            )
            assert app2.theme == data.get("theme")
