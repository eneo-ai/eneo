"""MCP Client for connecting to and executing HTTP-based MCP servers."""

import logging
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from intric.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Base exception for MCP client errors."""

    pass


class MCPClient:
    """Client for interacting with HTTP-based MCP servers."""

    def __init__(self, mcp_server: MCPServer, auth_credentials: dict[str, str] | None = None):
        """
        Initialize MCP client.

        Args:
            mcp_server: MCP server configuration
            auth_credentials: Authentication credentials from tenant settings
        """
        self.mcp_server = mcp_server
        self.auth_credentials = auth_credentials or {}
        self.session: Optional[ClientSession] = None
        self._streams_context = None
        self._session_context = None

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers based on server auth type."""
        headers = {}

        if self.mcp_server.http_auth_type == "bearer":
            token = self.auth_credentials.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"

        elif self.mcp_server.http_auth_type == "api_key":
            api_key = self.auth_credentials.get("api_key")
            key_header = self.auth_credentials.get("header_name", "X-API-Key")
            if api_key:
                headers[key_header] = api_key

        elif self.mcp_server.http_auth_type == "custom_headers":
            # Custom headers are passed directly from credentials
            headers.update(self.auth_credentials)

        return headers

    async def connect(self) -> None:
        """Connect to the HTTP-based MCP server."""
        try:
            headers = self._build_auth_headers()

            # Use SSE or Streamable HTTP based on transport type
            if self.mcp_server.transport_type == "sse":
                self._streams_context = sse_client(
                    url=self.mcp_server.http_url,
                    headers=headers
                )
            elif self.mcp_server.transport_type == "streamable_http":
                self._streams_context = streamablehttp_client(
                    url=self.mcp_server.http_url,
                    headers=headers
                )
            else:
                raise MCPClientError(f"Unsupported transport type: {self.mcp_server.transport_type}")

            # Enter the streams context
            streams = await self._streams_context.__aenter__()

            # For streamable_http, we get (read, write, session_id), for SSE we get (read, write)
            if self.mcp_server.transport_type == "streamable_http":
                read, write, session_id = streams
                logger.debug(f"Streamable HTTP session ID: {session_id}")
            else:
                read, write = streams

            # Create session
            self._session_context = ClientSession(read, write)
            self.session = await self._session_context.__aenter__()

            # Initialize the session
            await self.session.initialize()
            logger.info(f"Connected to MCP server: {self.mcp_server.name} via {self.mcp_server.transport_type}")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server {self.mcp_server.name}: {e}")
            raise MCPClientError(f"Connection failed: {e}")

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
            # Exit session context first
            if self._session_context:
                await self._session_context.__aexit__(None, None, None)
                self._session_context = None
                self.session = None

            # Then exit streams context
            if self._streams_context:
                await self._streams_context.__aexit__(None, None, None)
                self._streams_context = None

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
