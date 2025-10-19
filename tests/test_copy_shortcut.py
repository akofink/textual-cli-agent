import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from textual_cli_agent.ui.app import ChatApp, ChatView
from textual_cli_agent.providers.base import Provider, ProviderConfig, ToolSpec
from textual.widgets import TextArea


class DummyProvider(Provider):
    async def list_tools_format(self, tools: list[ToolSpec]) -> list[ToolSpec]:
        return tools

    async def completions_stream(
        self, messages: list[dict], tools: list[ToolSpec] | None = None
    ):
        if False:
            yield {}
        return
        yield  # pragma: no cover

    def build_assistant_message(self, text: str, tool_calls: list[dict]) -> dict:
        return {"role": "assistant", "content": text}

    def format_tool_result_message(self, tool_call_id: str, content: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


@pytest.mark.asyncio
async def test_ctrl_c_respects_textarea_focus() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            app = ChatApp(DummyProvider(ProviderConfig(model="x", api_key="key")))
            async with app.run_test() as pilot:
                await asyncio.sleep(0)
                tool_panel = app._get_tool_panel()
                assert tool_panel is not None
                tool_panel.start_turn(1)
                tool_panel.add_tool_call("call", "test", {"foo": "bar"})
                textarea = tool_panel.query_one("#tool_details", TextArea)

                await pilot.click("#tool_details")
                textarea.action_select_all()
                with patch.object(
                    app,
                    "_copy_text_to_clipboard",
                    return_value=True,
                ) as mock_copy:
                    await asyncio.sleep(0)
                    app.action_copy()
                    mock_copy.assert_called_with(
                        textarea.text,
                        "[ok] Tool details copied to clipboard",
                    )


@pytest.mark.asyncio
async def test_ctrl_c_falls_back_to_chat_copy(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            app = ChatApp(DummyProvider(ProviderConfig(model="x", api_key="key")))
            async with app.run_test():
                await asyncio.sleep(0)
                monkeypatch.setattr(app, "action_copy_chat", MagicMock())
                monkeypatch.setattr(
                    app, "_copy_text_to_clipboard", MagicMock(return_value=False)
                )
                app.action_copy()
                app.action_copy_chat.assert_called_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_copy_chat_fallback_creates_file(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.chdir(tmpdir)
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmpdir}):
            app = ChatApp(DummyProvider(ProviderConfig(model="x", api_key="key")))
            async with app.run_test():
                await asyncio.sleep(0)
                chat = app.query_one("#chat", ChatView)
                chat.append_block("Line 1")
                monkeypatch.setattr(
                    app, "_copy_text_to_clipboard", MagicMock(return_value=False)
                )
                app.action_copy_chat()
                exports = list(Path(tmpdir).glob("chat_export_*.txt"))
                assert exports
                exported = exports[0].read_text(encoding="utf-8")
                assert "Line 1" in exported
