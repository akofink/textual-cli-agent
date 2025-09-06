from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Tree, Static


@dataclass
class ToolCall:
    """Represents a single tool call with timing and results."""

    id: str
    name: str
    args: Dict[str, Any]
    result: Optional[Any] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error: Optional[str] = None

    @property
    def duration(self) -> Optional[float]:
        """Get call duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return None

    @property
    def status(self) -> str:
        """Get human-readable status."""
        if self.error:
            return "❌ Error"
        elif self.result is not None:
            return "✅ Complete"
        else:
            return "⏳ Running"


@dataclass
class ToolTurn:
    """Represents a conversation turn containing tool calls."""

    turn_id: int
    calls: List[ToolCall] = field(default_factory=list)
    is_parallel: bool = False
    start_time: float = field(default_factory=time.time)


class ToolCallDetails(Static):
    """Widget to display detailed information about a tool call."""

    def __init__(self, tool_call: ToolCall, session_start: float) -> None:
        self.tool_call = tool_call
        self.session_start = session_start
        super().__init__()
        self.update_content()

    def update_content(self) -> None:
        """Update the content display."""
        call = self.tool_call
        relative_time = call.start_time - self.session_start

        # Format args and result as pretty JSON
        try:
            args_json = json.dumps(call.args, indent=2) if call.args else "{}"
        except Exception:
            args_json = str(call.args)

        result_text = ""
        if call.error:
            result_text = f"[red]Error: {call.error}[/red]"
        elif call.result is not None:
            try:
                if isinstance(call.result, (str, int, float, bool)):
                    result_text = f"[green]{call.result}[/green]"
                else:
                    result_json = json.dumps(call.result, indent=2)
                    result_text = f"[green]{result_json}[/green]"
            except Exception:
                result_text = f"[green]{str(call.result)}[/green]"
        else:
            result_text = "[yellow]Running...[/yellow]"

        duration_text = ""
        if call.duration:
            duration_text = f"Duration: {call.duration:.2f}s"

        content = f"""[bold]{call.name}[/bold] {call.status}
ID: {call.id}
Time: +{relative_time:.1f}s {duration_text}

[bold]Arguments:[/bold]
{args_json}

[bold]Result:[/bold]
{result_text}"""

        self.update(content)


class ToolPanel(Container):
    """Interactive panel for displaying tool calls and results."""

    def __init__(self) -> None:
        super().__init__(id="tool_panel")
        self.session_start = time.time()
        self.turns: List[ToolTurn] = []
        self.current_turn: Optional[ToolTurn] = None
        self.visible = False

    def compose(self) -> ComposeResult:
        """Create the tool panel layout."""
        yield Vertical(
            Static("🔧 Tool Calls", id="tool_panel_header", classes="panel-header"),
            Tree("Tool Activity", id="tool_tree"),
            Static(
                "Click a tool call to see details",
                id="tool_details",
                classes="tool-details",
            ),
            classes="tool-panel-content",
        )

    def toggle_visibility(self) -> None:
        """Toggle the panel visibility."""
        self.visible = not self.visible
        if self.visible:
            self.add_class("visible")
        else:
            self.remove_class("visible")

        # Force layout refresh
        if self.app:
            self.app.refresh(layout=True)

    def start_turn(self, turn_id: int) -> None:
        """Start a new conversation turn."""
        self.current_turn = ToolTurn(turn_id=turn_id)
        self.turns.append(self.current_turn)
        self._update_tree()

    def add_tool_call(self, call_id: str, name: str, args: Dict[str, Any]) -> None:
        """Add a new tool call to the current turn."""
        if not self.current_turn:
            self.start_turn(len(self.turns))

        if self.current_turn:  # Type guard for mypy
            tool_call = ToolCall(id=call_id, name=name, args=args)
            self.current_turn.calls.append(tool_call)
            self._update_tree()

    def update_tool_result(
        self, call_id: str, result: Any = None, error: Optional[str] = None
    ) -> None:
        """Update a tool call with its result or error."""
        tool_call = self._find_tool_call(call_id)
        if tool_call:
            tool_call.end_time = time.time()
            if error:
                tool_call.error = error
            else:
                tool_call.result = result
            self._update_tree()

    def mark_parallel(self, call_ids: List[str]) -> None:
        """Mark tool calls as parallel execution."""
        if self.current_turn:
            self.current_turn.is_parallel = True
            self._update_tree()

    def _find_tool_call(self, call_id: str) -> Optional[ToolCall]:
        """Find a tool call by ID."""
        for turn in self.turns:
            for call in turn.calls:
                if call.id == call_id:
                    return call
        return None

    def _update_tree(self) -> None:
        """Update the tree display with current tool calls."""
        try:
            tree = self.query_one("#tool_tree", Tree)
            tree.clear()

            if not self.turns:
                tree.label = "No tool calls yet"
                return

            tree.label = f"Tool Activity ({len(self.turns)} turns)"

            for turn in self.turns:
                if not turn.calls:
                    continue

                # Create turn node
                turn_label = f"Turn {turn.turn_id}"
                if turn.is_parallel:
                    turn_label += " (Parallel)"
                turn_node = tree.root.add(
                    turn_label, data={"type": "turn", "turn": turn}
                )

                # Add tool calls
                for call in turn.calls:
                    call_label = f"{call.name} {call.status}"
                    if call.duration:
                        call_label += f" ({call.duration:.2f}s)"

                    turn_node.add(call_label, data={"type": "call", "call": call})

        except Exception:
            # Graceful fallback if tree update fails
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle tree node selection to show details."""
        try:
            details_widget = self.query_one("#tool_details", Static)

            if event.node.data and event.node.data.get("type") == "call":
                tool_call = event.node.data["call"]

                # Create detailed view
                detail_widget = ToolCallDetails(tool_call, self.session_start)
                details_widget.update(detail_widget.renderable)
            elif event.node.data and event.node.data.get("type") == "turn":
                turn = event.node.data["turn"]
                summary = f"Turn {turn.turn_id} - {len(turn.calls)} tool calls"
                if turn.is_parallel:
                    summary += " (parallel execution)"
                details_widget.update(summary)
            else:
                details_widget.update("Select a tool call to see details")

        except Exception:
            # Graceful fallback
            pass
