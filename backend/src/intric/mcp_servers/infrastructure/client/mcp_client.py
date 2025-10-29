"""MCP Client for connecting to and executing MCP servers."""

import asyncio
import logging
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from intric.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Base exception for MCP client errors."""

    pass


class MCPClient:
    """Client for interacting with MCP servers."""

    def __init__(self, mcp_server: MCPServer, env_vars: dict[str, str] | None = None):
        """
        Initialize MCP client.

        Args:
            mcp_server: MCP server configuration
            env_vars: Environment variables for the server
        """
        self.mcp_server = mcp_server
        self.env_vars = env_vars or {}
        self.session: Optional[ClientSession] = None
        self._read = None
        self._write = None

    async def connect(self) -> None:
        """Connect to the MCP server."""
        try:
            if self.mcp_server.server_type == "npm":
                await self._connect_npm()
            elif self.mcp_server.server_type == "uvx":
                await self._connect_uvx()
            elif self.mcp_server.server_type == "docker":
                await self._connect_docker()
            elif self.mcp_server.server_type == "http":
                await self._connect_http()
            else:
                raise MCPClientError(f"Unsupported server type: {self.mcp_server.server_type}")

            # Initialize the session
            await self.session.initialize()
            logger.info(f"Connected to MCP server: {self.mcp_server.name}")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server {self.mcp_server.name}: {e}")
            raise MCPClientError(f"Connection failed: {e}")

    async def _connect_npm(self) -> None:
        """Connect to NPM-based MCP server."""
        if not self.mcp_server.npm_package:
            raise MCPClientError("NPM package not specified")

        server_params = StdioServerParameters(
            command="npx",
            args=["-y", self.mcp_server.npm_package],
            env=self.env_vars,
        )

        self._read, self._write = await stdio_client(server_params).__aenter__()
        self.session = ClientSession(self._read, self._write)

    async def _connect_uvx(self) -> None:
        """Connect to UVX-based MCP server."""
        if not self.mcp_server.uvx_package:
            raise MCPClientError("UVX package not specified")

        server_params = StdioServerParameters(
            command="uvx",
            args=[self.mcp_server.uvx_package],
            env=self.env_vars,
        )

        self._read, self._write = await stdio_client(server_params).__aenter__()
        self.session = ClientSession(self._read, self._write)

    async def _connect_docker(self) -> None:
        """Connect to Docker-based MCP server."""
        if not self.mcp_server.docker_image:
            raise MCPClientError("Docker image not specified")

        # Docker MCP servers run via stdio too, but through docker run
        server_params = StdioServerParameters(
            command="docker",
            args=["run", "-i", "--rm", self.mcp_server.docker_image],
            env=self.env_vars,
        )

        self._read, self._write = await stdio_client(server_params).__aenter__()
        self.session = ClientSession(self._read, self._write)

    async def _connect_http(self) -> None:
        """Connect to HTTP-based MCP server."""
        # HTTP MCP servers use SSE transport
        # For now, we'll skip HTTP implementation as it requires different transport
        raise MCPClientError("HTTP MCP servers not yet supported")

    async def list_tools(self) -> list[dict[str, Any]]:
        """
        List all available tools from the MCP server.

        Returns:
            List of tool definitions
        """
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        try:
            response = await self.session.list_tools()
            tools = []

            for tool in response.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                })

            logger.debug(f"Listed {len(tools)} tools from {self.mcp_server.name}")
            return tools

        except Exception as e:
            logger.error(f"Failed to list tools from {self.mcp_server.name}: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            Tool execution result
        """
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        try:
            response = await self.session.call_tool(tool_name, arguments=arguments)

            # Extract content from response
            result = {
                "content": [],
                "is_error": False,
            }

            for content_item in response.content:
                if content_item.type == "text":
                    result["content"].append({
                        "type": "text",
                        "text": content_item.text,
                    })
                elif content_item.type == "image":
                    result["content"].append({
                        "type": "image",
                        "data": content_item.data,
                        "mime_type": content_item.mimeType,
                    })
                elif content_item.type == "resource":
                    result["content"].append({
                        "type": "resource",
                        "uri": content_item.uri,
                        "text": content_item.text if hasattr(content_item, "text") else None,
                    })

            if response.isError:
                result["is_error"] = True

            logger.info(f"Called tool {tool_name} on {self.mcp_server.name}")
            return result

        except Exception as e:
            logger.error(f"Failed to call tool {tool_name} on {self.mcp_server.name}: {e}")
            raise MCPClientError(f"Tool call failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        try:
            if self.session:
                # Clean up session
                self.session = None
                self._read = None
                self._write = None
                logger.info(f"Disconnected from MCP server: {self.mcp_server.name}")
        except Exception as e:
            logger.error(f"Error disconnecting from {self.mcp_server.name}: {e}")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
