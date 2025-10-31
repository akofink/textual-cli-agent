from __future__ import annotations

from typing import List

from .registry import tool
from ..todo_store import (
    add_todo as _add_todo,
    list_todos as _list_todos,
    remove_todo as _remove_todo,
    set_todo as _set_todo,
)


@tool(description="List TODO items.")
async def todo_list() -> List[str]:
    return await _list_todos()


@tool(description="Add a TODO item.")
async def todo_add(item: str) -> str:
    await _add_todo(item)
    return item


@tool(description="Remove a TODO item by 1-based index.")
async def todo_remove(index: int) -> bool:
    return await _remove_todo(max(0, index - 1))


@tool(description="Edit a TODO item by 1-based index.")
async def todo_edit(index: int, item: str) -> bool:
    return await _set_todo(max(0, index - 1), item)
