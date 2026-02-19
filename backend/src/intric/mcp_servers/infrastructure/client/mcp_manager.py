"""MCP Manager for handling multiple MCP server connections."""

import asyncio
import logging
from types import TracebackType
from typing import Any

from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.mcp_servers.infrastructure.client.mcp_client import MCPClient, MCPClientError

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages multiple MCP server connections and aggregates their tools."""

    def __init__(self):
        """Initialize MCP manager."""
        self.clients: dict[str, MCPClient] = {}
        self.tools: dict[str, dict[str, Any]] = {}  # tool_name -> tool_definition + mcp_server_id

    async def connect_servers(
        self, mcp_servers: list[MCPServer], env_vars_map: dict[str, dict[str, str]] | None = None
    ) -> None:
        """
        Connect to multiple MCP servers.

        Args:
            mcp_servers: List of MCP servers to connect to
            env_vars_map: Map of server ID to environment variables
        """
        env_vars_map = env_vars_map or {}

        # Connect to all servers in parallel
        connection_tasks: list[asyncio.Task[None]] = []
        for server in mcp_servers:
            env_vars = env_vars_map.get(str(server.id), {})
            client = MCPClient(server, env_vars)
            self.clients[str(server.id)] = client
            task = asyncio.create_task(self._connect_and_list_tools(client, str(server.id)))
            connection_tasks.append(task)

        # Wait for all connections
        await asyncio.gather(*connection_tasks, return_exceptions=True)

        logger.info(f"Connected to {len(self.clients)} MCP servers with {len(self.tools)} total tools")

    async def _connect_and_list_tools(self, client: MCPClient, server_id: str) -> None:
        """Connect to an MCP server and list its tools."""
        try:
            await client.connect()
            tools = await client.list_tools()

            # Register tools with server ID prefix to avoid name collisions
            for tool in tools:
                # Prefix tool name with server name to make it unique
                prefixed_name = f"{client.mcp_server.name.lower().replace(' ', '_')}_{tool['name']}"

                self.tools[prefixed_name] = {
                    **tool,
                    "mcp_server_id": server_id,
                    "mcp_server_name": client.mcp_server.name,
                    "original_tool_name": tool["name"],
                }

                logger.debug(f"Registered tool: {prefixed_name} from {client.mcp_server.name}")

        except MCPClientError as e:
            logger.error(f"Failed to connect to MCP server {server_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to MCP server {server_id}: {e}")

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        """
        Get all tools formatted for LLM function calling.

        Returns:
            List of tool definitions in OpenAI function calling format with metadata
        """
        llm_tools: list[dict[str, Any]] = []

        for tool_name, tool_def in self.tools.items():
            # Convert MCP tool schema to OpenAI function calling format
            llm_tool: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_def.get("description", ""),
                    "parameters": tool_def.get("input_schema", {"type": "object", "properties": {}}),
                },
                # Include metadata for display purposes
                "mcp_server_name": tool_def.get("mcp_server_name"),
                "original_tool_name": tool_def.get("original_tool_name"),
            }
            llm_tools.append(llm_tool)

        return llm_tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool by name.

        Args:
            tool_name: Prefixed tool name (e.g., "context7_search")
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        if tool_name not in self.tools:
            raise ValueError(f"Tool not found: {tool_name}")

        tool_def = self.tools[tool_name]
        server_id = tool_def["mcp_server_id"]
        original_tool_name = tool_def["original_tool_name"]

        if server_id not in self.clients:
            raise ValueError(f"MCP client not found for server: {server_id}")

        client = self.clients[server_id]

        try:
            result = await client.call_tool(original_tool_name, arguments)
            return result
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}")
            return {
                "content": [{"type": "text", "text": f"Error executing tool: {str(e)}"}],
                "is_error": True,
            }

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        disconnect_tasks = [client.disconnect() for client in self.clients.values()]
        await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        self.clients.clear()
        self.tools.clear()
        logger.info("Disconnected from all MCP servers")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.disconnect_all()
