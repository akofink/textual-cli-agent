from __future__ import annotations

from typing import List, Dict
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Tree, Static


@dataclass
class TodoItem:
    """Represents a todo item."""

    content: str
    status: str  # "pending", "in_progress", "completed"
    active_form: str


class TodoPanel(Container):
    """Interactive panel for displaying todo items."""

    def __init__(self) -> None:
        super().__init__(id="todo_panel")
        self.todos: List[TodoItem] = []
        self.visible = False

    def compose(self) -> ComposeResult:
        """Create the todo panel layout."""
        yield Vertical(
            Static("📝 Todo List", id="todo_panel_header", classes="panel-header"),
            Tree("Tasks", id="todo_tree"),
            Static(
                "Click a task to see details",
                id="todo_details",
                classes="todo-details",
            ),
            classes="todo-panel-content",
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

    def update_todos(self, todos: List[str]) -> None:
        """Update the todo list from simple string list."""
        self.todos = [
            TodoItem(
                content=todo,
                status="pending",  # Default status for simple todos
                active_form=f"Working on: {todo}",
            )
            for todo in todos
        ]
        self._update_tree()

    def update_structured_todos(self, todos: List[Dict[str, str]]) -> None:
        """Update the todo list from structured external data."""
        self.todos = [
            TodoItem(
                content=todo["content"],
                status=todo["status"],
                active_form=todo["activeForm"],
            )
            for todo in todos
        ]
        self._update_tree()

    def _update_tree(self) -> None:
        """Update the tree display with current todos."""
        try:
            tree = self.query_one("#todo_tree", Tree)
            tree.clear()

            if not self.todos:
                tree.label = "No tasks yet"
                return

            completed_count = sum(
                1 for todo in self.todos if todo.status == "completed"
            )
            tree.label = f"Tasks ({completed_count}/{len(self.todos)} complete)"

            # Group by status
            pending = [t for t in self.todos if t.status == "pending"]
            in_progress = [t for t in self.todos if t.status == "in_progress"]
            completed = [t for t in self.todos if t.status == "completed"]

            if in_progress:
                progress_node = tree.root.add("🔄 In Progress", data={"type": "group"})
                for todo in in_progress:
                    progress_node.add(
                        f"⚡ {todo.content}", data={"type": "todo", "todo": todo}
                    )

            if pending:
                pending_node = tree.root.add("📋 Pending", data={"type": "group"})
                for todo in pending:
                    pending_node.add(
                        f"⏸️ {todo.content}", data={"type": "todo", "todo": todo}
                    )

            if completed:
                completed_node = tree.root.add("✅ Completed", data={"type": "group"})
                for todo in completed:
                    completed_node.add(
                        f"✓ {todo.content}", data={"type": "todo", "todo": todo}
                    )

        except Exception:
            # Graceful fallback if tree update fails
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle tree node selection to show details."""
        try:
            details_widget = self.query_one("#todo_details", Static)

            if event.node.data and event.node.data.get("type") == "todo":
                todo = event.node.data["todo"]
                status_emoji = {"pending": "⏸️", "in_progress": "⚡", "completed": "✅"}

                details = f"""[bold]{status_emoji.get(todo.status, "")} {todo.content}[/bold]

Status: {todo.status.replace("_", " ").title()}
Active Form: {todo.active_form}"""

                details_widget.update(details)
            elif event.node.data and event.node.data.get("type") == "group":
                details_widget.update("Task group - select a specific task for details")
            else:
                details_widget.update("Select a task to see details")

        except Exception:
            # Graceful fallback
            pass
