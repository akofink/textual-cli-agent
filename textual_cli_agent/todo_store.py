from __future__ import annotations

import asyncio
from typing import List

# Simple in-memory todo store with async lock
_todos: List[str] = []
_lock = asyncio.Lock()


async def list_todos() -> List[str]:
    async with _lock:
        return list(_todos)


async def add_todo(item: str) -> None:
    async with _lock:
        _todos.append(item)


async def remove_todo(index: int) -> bool:
    async with _lock:
        if 0 <= index < len(_todos):
            _todos.pop(index)
            return True
        return False


async def set_todo(index: int, item: str) -> bool:
    async with _lock:
        if 0 <= index < len(_todos):
            _todos[index] = item
            return True
        return False
