import pytest

from textual_cli_agent.tools import tool, get_tool_specs, execute_tool


@pytest.mark.asyncio
async def test_tool_registration_and_execution():
    @tool()
    def add_test(a: int, b: int) -> int:
        return a + b

    specs = get_tool_specs()
    assert any(s["name"] == "add_test" for s in specs)

    result = await execute_tool("add_test", {"a": 2, "b": 3})
    assert result == 5
