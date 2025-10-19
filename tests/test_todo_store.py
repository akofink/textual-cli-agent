from __future__ import annotations


import pytest

from textual_cli_agent import todo_store


@pytest.mark.asyncio
async def test_todo_store_operations() -> None:
    # ensure clean state
    while await todo_store.remove_todo(0):
        pass

    await todo_store.add_todo("first")
    await todo_store.add_todo("second")
    todos = await todo_store.list_todos()
    assert todos == ["first", "second"]

    assert await todo_store.set_todo(0, "updated")
    assert not await todo_store.set_todo(5, "missing")

    assert await todo_store.remove_todo(1)
    assert not await todo_store.remove_todo(10)
    assert await todo_store.list_todos() == ["updated"]
