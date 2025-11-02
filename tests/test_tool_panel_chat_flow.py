import asyncio
import json
import tempfile
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from textual.widgets import Input, Tree

from textual_cli_agent.engine import AgentEngine
from textual_cli_agent.providers.base import Provider, ProviderConfig, ToolSpec
from textual_cli_agent.ui.app import ChatApp
from textual_cli_agent.ui.tool_panel import ToolTurn


class MultiCallProvider(Provider):
    """Provider stub that emits multiple tool calls in a single chat turn."""

    def __init__(self, cfg: ProviderConfig) -> None:
        super().__init__(cfg)
        self._invocations = 0

    async def list_tools_format(self, tools: List[ToolSpec]) -> Any:
        return tools

    async def completions_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolSpec]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        if self._invocations == 0:
            self._invocations += 1
            yield {
                "type": "tool_call",
                "id": "call-1",
                "name": "tool_alpha",
                "arguments": {"foo": 1},
            }
            yield {
                "type": "tool_call",
                "id": "call-2",
                "name": "tool_beta",
                "arguments": {"bar": 2},
            }
        else:
            self._invocations += 1
            yield {"type": "text", "delta": "all done"}

    def build_assistant_message(
        self, text: str, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        formatted_calls: List[Dict[str, Any]] = []
        for call in tool_calls:
            formatted_calls.append({
                "id": call.get("id"),
                "function": {
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("arguments", {})),
                },
            })
        return {"role": "assistant", "content": text, "tool_calls": formatted_calls}

    def format_tool_result_message(
        self, tool_call_id: str, content: str
    ) -> Dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


class ReusedIdProvider(Provider):
    """Provider stub that reuses tool call identifiers each turn."""

    def __init__(self, cfg: ProviderConfig) -> None:
        super().__init__(cfg)
        self._invocations = 0

    async def list_tools_format(self, tools: List[ToolSpec]) -> Any:
        return tools

    async def completions_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolSpec]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        self._invocations += 1
        yield {
            "type": "tool_call",
            "id": "call-1",
            "name": f"tool_turn_{self._invocations}",
            "arguments": {"value": self._invocations},
        }
        yield {"type": "round_complete", "had_tool_calls": True}

    def build_assistant_message(
        self, text: str, tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        formatted_calls: List[Dict[str, Any]] = []
        for call in tool_calls:
            formatted_calls.append({
                "id": call.get("id"),
                "function": {
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("arguments", {})),
                },
            })
        return {"role": "assistant", "content": text, "tool_calls": formatted_calls}

    def format_tool_result_message(
        self, tool_call_id: str, content: str
    ) -> Dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


async def _wait_for_calls(app: ChatApp, expected_call_count: int) -> ToolTurn:
    """Wait until the tool panel records the expected number of calls."""
    for _ in range(60):
        panel = app._get_tool_panel()
        if panel:
            for turn in panel.turns:
                if len(turn.calls) >= expected_call_count:
                    return turn
        await asyncio.sleep(0.05)
    raise AssertionError("Timed out waiting for tool panel updates")


async def _drain_worker(app: ChatApp) -> None:
    """Wait for the background worker queue to drain."""
    for _ in range(60):
        if app._pending_count == 0 and app._queue.empty():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Worker did not finish processing prompts")


@pytest.mark.asyncio
async def test_tool_panel_appends_multiple_calls_in_single_chat(monkeypatch) -> None:
    """Ensure the tool panel accumulates multiple tool calls within one chat."""

    async def fake_execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "name": name, "args": args}

    monkeypatch.setattr(AgentEngine, "_execute_tool_safely", fake_execute)
    monkeypatch.setattr(AgentEngine, "_combined_tool_specs", lambda self: [])

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("XDG_CONFIG_HOME", tmpdir)

        provider = MultiCallProvider(ProviderConfig(model="dummy", api_key="dummy-key"))
        app = ChatApp(provider=provider)
        app.auto_continue = False

        async with app.run_test():
            app.auto_continue = False
            await asyncio.sleep(0)
            input_widget = app.query_one("#input", Input)

            class DummyEvent:
                def __init__(self, value: str, input_widget: Input) -> None:
                    self.value = value
                    self.input = input_widget

            input_widget.value = "show tools"
            event = DummyEvent("show tools", input_widget)
            await app.on_input_submitted(event)

            await _drain_worker(app)
            turn = await _wait_for_calls(app, expected_call_count=2)

            call_ids = [call.id for call in turn.calls]
            assert call_ids == ["call-1", "call-2"]
            call_names = [call.name for call in turn.calls]
            assert call_names == ["tool_alpha", "tool_beta"]

            panel = app._get_tool_panel()
            assert panel is not None
            tree = panel.query_one("#tool_tree", Tree)
            root = tree.root
            assert root is not None
            turn_nodes = [node for node in root.children if node.children]
            assert turn_nodes, "expected tool turn nodes in the tree"
            first_turn_node = turn_nodes[0]
            assert len(first_turn_node.children) == 2


@pytest.mark.asyncio
async def test_tool_panel_handles_reused_call_ids(monkeypatch) -> None:
    """Providers often reuse tool IDs each turn; ensure we still record every call."""

    async def fake_execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "args": args}

    monkeypatch.setattr(AgentEngine, "_execute_tool_safely", fake_execute)
    monkeypatch.setattr(AgentEngine, "_combined_tool_specs", lambda self: [])

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("XDG_CONFIG_HOME", tmpdir)

        provider = ReusedIdProvider(ProviderConfig(model="dummy", api_key="dummy-key"))
        app = ChatApp(provider=provider)
        app.auto_continue = False

        async with app.run_test():
            app.auto_continue = False
            await asyncio.sleep(0)
            input_widget = app.query_one("#input", Input)

            class DummyEvent:
                def __init__(self, value: str, input_widget: Input) -> None:
                    self.value = value
                    self.input = input_widget

            # First prompt
            await app.on_input_submitted(DummyEvent("turn one", input_widget))
            await _drain_worker(app)
            first_turn = await _wait_for_calls(app, expected_call_count=1)
            assert [call.id for call in first_turn.calls] == ["call-1"]

            # Second prompt, same tool ID returned by provider
            await app.on_input_submitted(DummyEvent("turn two", input_widget))
            await _drain_worker(app)

            panel = app._get_tool_panel()
            assert panel is not None
            assert len(panel.turns) >= 2
            second_turn = panel.turns[-1]
            assert [call.id for call in second_turn.calls] == ["call-1"]
            assert [call.name for call in second_turn.calls] == ["tool_turn_2"]
