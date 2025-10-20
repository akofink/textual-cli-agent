from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static, Tree, TextArea


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


def _format_tool_call_details(tool_call: ToolCall, session_start: float) -> str:
    """Format tool call details as plain text."""
    relative_time = tool_call.start_time - session_start
    duration_text = ""
    if tool_call.duration:
        duration_text = f"{tool_call.duration:.2f}s"

    try:
        args_json = json.dumps(tool_call.args, indent=2) if tool_call.args else "{}"
    except Exception:
        args_json = str(tool_call.args)

    if tool_call.error:
        result_text = f"Error: {tool_call.error}"
    elif tool_call.result is not None:
        try:
            if isinstance(tool_call.result, (str, int, float, bool)):
                result_text = str(tool_call.result)
            else:
                result_text = json.dumps(tool_call.result, indent=2)
        except Exception:
            result_text = str(tool_call.result)
    else:
        result_text = "Running..."

    return (
        f"{tool_call.name} {tool_call.status}\n"
        f"ID: {tool_call.id}\n"
        f"Time: +{relative_time:.1f}s"
        f"{f' Duration: {duration_text}' if duration_text else ''}\n\n"
        f"Arguments:\n{args_json}\n\n"
        f"Result:\n{result_text}"
    )


class ToolPanel(Container):
    """Interactive panel for displaying tool calls and results."""

    def __init__(self) -> None:
        super().__init__(id="tool_panel")
        self.session_start = time.time()
        self.turns: List[ToolTurn] = []
        self.current_turn: Optional[ToolTurn] = None
        self.visible = False
        self._selected_call_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        """Create the tool panel layout."""
        yield Vertical(
            Static("🔧 Tool Calls", id="tool_panel_header", classes="panel-header"),
            Tree("Tool Activity", id="tool_tree"),
            TextArea(
                "Select a tool call to see details",
                id="tool_details",
                classes="tool-details",
                read_only=True,
                show_line_numbers=False,
                soft_wrap=True,
                tab_behavior="focus",
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

        existing = self._find_tool_call(call_id)
        if existing:
            existing.args = args
            if self._selected_call_id == call_id:
                self._show_call_details(existing)
            self._update_tree()
            return

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
            if self._selected_call_id == call_id:
                self._show_call_details(tool_call)

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
            root = tree.root
            if root is None:
                return

            if not self.turns:
                root.label = "No tool calls yet"
                return

            root.label = f"Tool Activity ({len(self.turns)} turns)"

            selected_node = None

            for turn in self.turns:
                if not turn.calls:
                    continue

                # Create turn node
                turn_label = f"Turn {turn.turn_id}"
                if turn.is_parallel:
                    turn_label += " (Parallel)"
                turn_node = root.add(turn_label, data={"type": "turn", "turn": turn})

                # Add tool calls
                for call in turn.calls:
                    call_label = f"{call.name} {call.status}"
                    if call.duration:
                        call_label += f" ({call.duration:.2f}s)"

                    node = turn_node.add(
                        call_label, data={"type": "call", "call": call}
                    )
                    if call.id == self._selected_call_id:
                        selected_node = node

            if self._selected_call_id and not selected_node:
                # Selected call no longer present; reset selection and details
                self._selected_call_id = None
                try:
                    details_widget = self.query_one("#tool_details", TextArea)
                    details_widget.load_text("Select a tool call to see details")
                except Exception:
                    pass
            elif selected_node is not None:
                try:
                    tree.select_node(selected_node)
                except Exception:
                    pass

        except Exception:
            # Graceful fallback if tree update fails
            pass

    def _show_call_details(
        self, tool_call: ToolCall, details_widget: Optional[TextArea] = None
    ) -> None:
        """Render detailed information for a tool call."""
        try:
            widget = details_widget or self.query_one("#tool_details", TextArea)
            widget.load_text(_format_tool_call_details(tool_call, self.session_start))
        except Exception:
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle tree node selection to show details."""
        try:
            details_widget = self.query_one("#tool_details", TextArea)

            node_data = event.node.data or {}
            if node_data.get("type") == "call":
                tool_call = node_data["call"]
                self._selected_call_id = tool_call.id
                self._show_call_details(tool_call, details_widget)
            elif node_data.get("type") == "turn":
                self._selected_call_id = None
                turn = node_data["turn"]
                summary = f"Turn {turn.turn_id} - {len(turn.calls)} tool calls"
                if turn.is_parallel:
                    summary += " (parallel execution)"
                details_widget.load_text(summary)
            else:
                self._selected_call_id = None
                details_widget.load_text("Select a tool call to see details")

        except Exception:
            # Graceful fallback
            pass
