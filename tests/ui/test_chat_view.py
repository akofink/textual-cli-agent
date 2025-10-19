from __future__ import annotations

import pytest

from textual import events
from textual.app import App, ComposeResult

from textual_cli_agent.ui.app import ChatView


class _ChatTestApp(App):
    def compose(self) -> ComposeResult:
        yield ChatView(id="chat")


@pytest.mark.asyncio
async def test_chat_view_mouse_selection() -> None:
    async with _ChatTestApp().run_test() as pilot:
        chat = pilot.app.query_one(ChatView)
        chat.append_block("Hello world\nSecond line")
        await pilot.pause()

        await pilot._post_mouse_events([events.MouseDown], chat, offset=(1, 0))
        await pilot._post_mouse_events([events.MouseMove], chat, offset=(5, 0))
        await pilot._post_mouse_events([events.MouseUp], chat, offset=(5, 0))

        selection = chat.text_selection
        assert selection is not None
        text, _ = chat.get_selection(selection)
        assert text == "ello"


@pytest.mark.asyncio
async def test_chat_view_get_text_fallback_and_selection_across_lines() -> None:
    async with _ChatTestApp().run_test() as pilot:
        chat = pilot.app.query_one(ChatView)
        chat.append_text("Line one")
        chat.append_block("\nLine two")
        await pilot.pause()

        # ensure fallback returns concatenated text
        full_text = chat.get_text()
        assert "Line one" in full_text
        assert "Line two" in full_text

        # select a region on the second line to ensure metadata survives highlighting
        await pilot._post_mouse_events([events.MouseDown], chat, offset=(1, 1))
        await pilot._post_mouse_events([events.MouseMove], chat, offset=(5, 1))
        await pilot._post_mouse_events([events.MouseUp], chat, offset=(5, 1))

        selection = chat.text_selection
        assert selection is not None
        selected_text = selection.extract(chat.get_text())
        assert selected_text.strip()
