import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Tree, TextArea

from textual_cli_agent.ui.tool_panel import (
    ToolCall,
    ToolPanel,
    _format_tool_call_details,
)


class ToolPanelTestApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.panel = ToolPanel()

    def compose(self) -> ComposeResult:
        yield self.panel


@pytest.mark.asyncio
async def test_tool_panel_shows_details_and_errors() -> None:
    app = ToolPanelTestApp()
    async with app.run_test():
        panel = app.panel
        panel.start_turn(1)
        panel.add_tool_call("call_1", "test_tool", {"foo": "bar"})

        tree = panel.query_one("#tool_tree", Tree)
        root = tree.root
        assert root is not None
        call_node = root.children[0].children[0]
        panel.on_tree_node_selected(Tree.NodeSelected(call_node))

        details = panel.query_one("#tool_details", TextArea)
        initial_text = details.text
        assert "test_tool" in initial_text
        assert "foo" in initial_text

        panel.update_tool_result("call_1", error="boom")
        await asyncio.sleep(0)
        updated_text = details.text
        assert "boom" in updated_text


@pytest.mark.asyncio
async def test_tool_panel_selection_persists_after_update() -> None:
    app = ToolPanelTestApp()
    async with app.run_test():
        panel = app.panel
        panel.start_turn(1)
        panel.add_tool_call("call_1", "test_tool", {"foo": "bar"})

        tree = panel.query_one("#tool_tree", Tree)
        root = tree.root
        assert root is not None
        turn_node = root.children[0]
        call_node = turn_node.children[0]
        tree.select_node(call_node)
        panel.on_tree_node_selected(Tree.NodeSelected(call_node))
        assert panel._selected_call_id == "call_1"

        panel.update_tool_result("call_1", result={"ok": True})
        await asyncio.sleep(0)
        assert panel._selected_call_id == "call_1"
        details = panel.query_one("#tool_details", TextArea)
        assert "ok" in details.text


@pytest.mark.asyncio
async def test_tool_panel_clears_missing_selection() -> None:
    app = ToolPanelTestApp()
    async with app.run_test():
        panel = app.panel
        await asyncio.sleep(0)
        panel._selected_call_id = "missing"
        panel._update_tree()
        await asyncio.sleep(0)
        details = panel.query_one("#tool_details", TextArea)
        assert "Select a tool call" in details.text


@pytest.mark.asyncio
async def test_tool_panel_updates_existing_call_args() -> None:
    app = ToolPanelTestApp()
    async with app.run_test():
        panel = app.panel
        panel.start_turn(1)
        panel.add_tool_call("call_1", "demo", {"value": 1})
        panel.add_tool_call("call_1", "demo", {"value": 2})

        assert panel.current_turn is not None
        assert len(panel.current_turn.calls) == 1
        call = panel.current_turn.calls[0]
        assert call.args == {"value": 2}


def test_format_tool_call_details_includes_error() -> None:
    call = ToolCall(
        id="xyz",
        name="demo",
        args={"foo": "bar"},
        result=None,
        error="boom",
        start_time=1.0,
        end_time=1.5,
    )
    formatted = _format_tool_call_details(call, session_start=0.0)
    assert "demo ❌ Error" in formatted
    assert "Error: boom" in formatted
    assert "Duration: 0.50s" in formatted
