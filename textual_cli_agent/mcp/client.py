from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from mcp import Client
    from mcp.transport.stdio import StdioServerParameters, stdio_client
    from mcp.transport.http import http_client
except Exception:  # pragma: no cover - SDK optional
    Client = None
    StdioServerParameters = None
    stdio_client = None
    http_client = None


@dataclass
class McpTool:
    name: str
    description: str
    parameters: Dict[str, Any]


class McpManager:
    def __init__(self) -> None:
        self.clients: List[Any] = []
        self.tools: List[McpTool] = []

    async def start(
        self,
        stdio_cmds: List[str] | None = None,
        http_urls: List[str] | None = None,
        grpc_endpoints: List[str] | None = None,  # scaffold
    ) -> None:
        if Client is None:
            return  # MCP not available, noop
        stdio_cmds = stdio_cmds or []
        http_urls = http_urls or []

        # Start stdio servers
        for cmd in stdio_cmds:
            # Let the MCP SDK manage the process lifecycle; no need to pre-spawn ourselves
            params = StdioServerParameters(command=cmd)
            client = await stdio_client(params)
            self.clients.append(client)

        # Connect HTTP servers
        for url in http_urls:
            client = await http_client(url)
            self.clients.append(client)

        # Collect tools from servers
        for client in self.clients:
            try:
                tools = await client.list_tools()
                for t in tools:
                    self.tools.append(
                        McpTool(name=t.name, description=t.description or "", parameters=t.input_schema or {"type": "object"})
                    )
            except Exception:
                continue

    async def stop(self) -> None:
        for client in self.clients:
            try:
                await client.close()
            except Exception:
                pass
        self.clients.clear()
        self.tools.clear()

    def tool_specs(self) -> List[Dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self.tools
        ]

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        # naive: call the first client that has the tool
        for client in self.clients:
            try:
                return await client.call_tool(name, arguments)
            except Exception:
                continue
        raise KeyError(f"MCP tool not found: {name}")
