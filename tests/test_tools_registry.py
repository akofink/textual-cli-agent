from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from textual_cli_agent import tools
from textual_cli_agent.tools import (
    tool,
    get_tool_specs,
    execute_tool,
    _annotation_to_schema,
    parallel_run,
    http_get,
    file_read,
)


@pytest.fixture(autouse=True)
def clear_tool_registry():
    original = tools._TOOL_REGISTRY.copy()
    tools._TOOL_REGISTRY.clear()
    try:
        yield
    finally:
        tools._TOOL_REGISTRY.clear()
        tools._TOOL_REGISTRY.update(original)


@pytest.mark.asyncio
async def test_tool_registration_and_execution():
    @tool()
    def add_test(a: int, b: int) -> int:
        return a + b

    specs = get_tool_specs()
    assert any(s["name"] == "add_test" for s in specs)

    result = await execute_tool("add_test", {"a": 2, "b": 3})
    assert result == 5


def test_annotation_to_schema_variants(tmp_path: Path) -> None:
    class Payload(BaseModel):
        values: List[int]

    pydantic_schema = _annotation_to_schema(Payload)
    assert pydantic_schema["title"] == "Payload"

    list_schema = _annotation_to_schema(List[str])
    assert list_schema["items"]["type"] == "string"

    dict_schema = _annotation_to_schema(dict)
    assert dict_schema["type"] == "string"

    number_schema = _annotation_to_schema(int)
    assert number_schema["type"] == "integer"

    # file_read utility
    sample = tmp_path / "example.txt"
    sample.write_text("hello", encoding="utf-8")
    assert file_read(str(sample)) == "hello"


@pytest.mark.asyncio
async def test_parallel_run_handles_errors():
    @tool()
    async def echo(value: str) -> str:
        return value

    results = await parallel_run([
        tools.ParallelTask(tool="echo", arguments={"value": "ok"}),
        tools.ParallelTask(tool="missing", arguments={}),
    ])
    assert results[0] == "ok"
    assert isinstance(results[1], dict) and "error" in results[1]


@pytest.mark.asyncio
async def test_http_get_makes_request(monkeypatch):
    client = AsyncMock()
    response = AsyncMock()
    response.text = "data"
    response.raise_for_status = lambda: None
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    context.__aexit__.return_value = False

    with patch("httpx.AsyncClient", return_value=context):
        content = await http_get("https://example.com", headers={"X-Test": "y"})
        assert content == "data"
        client.get.assert_awaited_once()
