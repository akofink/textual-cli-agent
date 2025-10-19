from __future__ import annotations

from types import SimpleNamespace

import pytest

from textual_cli_agent.mcp.client import McpManager


@pytest.mark.asyncio
async def test_mcp_manager_start_no_package(monkeypatch):
    manager = McpManager()
    monkeypatch.setattr("textual_cli_agent.mcp.client.MCP_AVAILABLE", False)
    await manager.start()
    assert manager.clients == []


class _StubClient:
    def __init__(self, tools):
        self._tools = tools
        self.closed = False

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments):
        if name == "fails":
            raise RuntimeError("fail")
        return {"name": name, "args": arguments}

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_mcp_manager_full_flow(monkeypatch):
    manager = McpManager()
    monkeypatch.setattr("textual_cli_agent.mcp.client.MCP_AVAILABLE", True)

    stub_client = _StubClient([
        SimpleNamespace(
            name="tool_a", description="desc", input_schema={"type": "object"}
        )
    ])

    class _Params:
        def __init__(self, command: str):
            self.command = command

    async def fake_stdio_client(params):
        assert params.command == "cmd"
        return stub_client

    monkeypatch.setattr("textual_cli_agent.mcp.client.StdioServerParameters", _Params)
    monkeypatch.setattr("textual_cli_agent.mcp.client.stdio_client", fake_stdio_client)
    monkeypatch.setattr("textual_cli_agent.mcp.client.http_client", None)

    await manager.start(stdio_cmds=["cmd"], http_urls=["http://example.com"])
    assert len(manager.clients) == 1
    assert manager.tool_specs()[0]["name"] == "tool_a"

    result = await manager.execute("tool_a", {"foo": "bar"})
    assert result["args"] == {"foo": "bar"}

    with pytest.raises(KeyError):
        await manager.execute("fails", {})

    # Ensure stop closes client
    await manager.stop()
    assert stub_client.closed
    assert manager.clients == []
    assert manager.tools == []


@pytest.mark.asyncio
async def test_mcp_execute_all_clients_fail(monkeypatch):
    manager = McpManager()
    manager.clients = [_StubClient([])]
    with pytest.raises(KeyError):
        await manager.execute("fails", {})
