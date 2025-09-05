from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List
from ..providers.base import ToolSpec

logger = logging.getLogger(__name__)

try:
    from mcp import Client  # type: ignore[import-not-found,attr-defined]
    from mcp.transport.stdio import StdioServerParameters, stdio_client  # type: ignore[import-not-found]
    from mcp.transport.http import http_client  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - SDK optional
    Client = None  # type: ignore[misc,assignment]
    StdioServerParameters = None  # type: ignore[misc,assignment]
    stdio_client = None  # type: ignore[misc,assignment]
    http_client = None  # type: ignore[misc,assignment]


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
            logger.warning("MCP SDK not available, skipping MCP connections")
            return  # MCP not available, noop

        stdio_cmds = stdio_cmds or []
        http_urls = http_urls or []

        # Start stdio servers
        for cmd in stdio_cmds:
            try:
                logger.info(f"Starting MCP stdio server: {cmd}")
                # Let the MCP SDK manage the process lifecycle; no need to pre-spawn ourselves
                params = StdioServerParameters(command=cmd)
                client = await stdio_client(params)
                self.clients.append(client)
                logger.info(f"Successfully connected to stdio server: {cmd}")
            except Exception as e:
                logger.error(f"Failed to connect to stdio MCP server {cmd}: {e}")
                continue

        # Connect HTTP servers
        for url in http_urls:
            try:
                logger.info(f"Connecting to MCP HTTP server: {url}")
                client = await http_client(url)
                self.clients.append(client)
                logger.info(f"Successfully connected to HTTP server: {url}")
            except Exception as e:
                logger.error(f"Failed to connect to HTTP MCP server {url}: {e}")
                continue

        # Collect tools from servers
        successful_clients = []
        for i, client in enumerate(self.clients):
            try:
                logger.info(f"Listing tools from MCP client {i}")
                tools = await client.list_tools()
                logger.info(f"Found {len(tools)} tools from client {i}")
                for t in tools:
                    try:
                        tool_name = getattr(
                            t, "name", f"unknown_tool_{len(self.tools)}"
                        )
                        tool_desc = getattr(t, "description", "") or ""
                        tool_schema = getattr(t, "input_schema", None) or {
                            "type": "object"
                        }

                        self.tools.append(
                            McpTool(
                                name=tool_name,
                                description=tool_desc,
                                parameters=tool_schema,
                            )
                        )
                        logger.debug(f"Added MCP tool: {tool_name}")
                    except Exception as e:
                        logger.error(f"Error processing tool {t}: {e}")
                        continue
                successful_clients.append(client)
            except Exception as e:
                logger.error(f"Failed to list tools from MCP client {i}: {e}")
                # Don't add failed clients to successful list
                try:
                    await client.close()
                except Exception:
                    pass
                continue

        # Replace clients list with only successful ones
        self.clients = successful_clients
        logger.info(
            f"MCP initialization complete: {len(self.clients)} clients, {len(self.tools)} tools"
        )

    async def stop(self) -> None:
        for client in self.clients:
            try:
                await client.close()
            except Exception:
                pass
        self.clients.clear()
        self.tools.clear()

    def tool_specs(self) -> List[ToolSpec]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self.tools
        ]

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        # Try each client that might have the tool
        if not self.clients:
            raise KeyError(f"No MCP clients available for tool: {name}")

        last_exception = None
        for i, client in enumerate(self.clients):
            try:
                logger.debug(f"Attempting to execute tool {name} with client {i}")
                result = await client.call_tool(name, arguments)
                logger.debug(f"Successfully executed tool {name} with client {i}")
                return result
            except Exception as e:
                logger.debug(f"Tool {name} failed with client {i}: {e}")
                last_exception = e
                continue

        # If we get here, all clients failed
        error_msg = f"MCP tool '{name}' failed on all clients"
        if last_exception:
            error_msg += f". Last error: {str(last_exception)}"
        logger.error(error_msg)
        raise KeyError(error_msg)
