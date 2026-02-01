"""MCP Client for connecting to and executing HTTP-based MCP servers."""

import asyncio
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from intric.main.logging import get_logger
from intric.mcp_servers.domain.entities.mcp_server import MCPServer

logger = get_logger(__name__)

# Default connection timeout in seconds
MCP_CONNECTION_TIMEOUT_DEFAULT = 30


class MCPClientError(Exception):
    """Base exception for MCP client errors."""

    pass


class MCPClient:
    """Client for interacting with HTTP-based MCP servers."""

    def __init__(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None,
        timeout: int | None = None,
    ):
        """
        Initialize MCP client.

        Args:
            mcp_server: MCP server configuration
            auth_credentials: Authentication credentials from tenant settings
            timeout: Connection timeout in seconds (defaults to 30s)
        """
        self.mcp_server = mcp_server
        self.auth_credentials = auth_credentials or {}
        self.timeout = timeout or MCP_CONNECTION_TIMEOUT_DEFAULT
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
            await asyncio.wait_for(
                self._connect_internal(),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Connection to MCP server {self.mcp_server.name} timed out after {self.timeout}s")
            # Clean up any partially initialized contexts
            await self._cleanup_contexts()
            raise MCPClientError(f"Connection timed out after {self.timeout}s")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {self.mcp_server.name}: {e}")
            await self._cleanup_contexts()
            raise MCPClientError(f"Connection failed: {e}")

    async def _cleanup_contexts(self) -> None:
        """Clean up any partially initialized contexts."""
        try:
            if self._session_context:
                await self._session_context.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            self._session_context = None
            self.session = None

        try:
            if self._streams_context:
                await self._streams_context.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            self._streams_context = None

    async def _connect_internal(self) -> None:
        """Internal connection logic."""
        headers = self._build_auth_headers()

        # Create the streamable HTTP context manager
        streams_context = streamablehttp_client(
            url=self.mcp_server.http_url,
            headers=headers
        )

        # Enter the streams context - only save reference after successful entry
        # This prevents cleanup attempts on partially-initialized contexts (anyio 4.x fix)
        try:
            streams = await streams_context.__aenter__()
        except Exception:
            # Failed during __aenter__ - don't save context, don't try to cleanup
            # Let GC handle the partially initialized context
            raise

        # Successfully entered - now save the reference
        self._streams_context = streams_context
        read, write, session_id = streams
        logger.debug(f"Streamable HTTP session ID: {session_id}")

        # Create and enter session context
        session_context = ClientSession(read, write)
        try:
            session = await session_context.__aenter__()
        except Exception:
            # Session entry failed - cleanup streams context only
            try:
                await streams_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._streams_context = None
            raise

        # Successfully entered - save references
        self._session_context = session_context
        self.session = session

        # Initialize the session
        await self.session.initialize()
        logger.info(f"Connected to MCP server: {self.mcp_server.name}")

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
            raise MCPClientError(f"Failed to list tools: {e}")

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
        """Disconnect from the MCP server.

        Note: Due to anyio's task boundary restrictions, cleanup may fail if
        disconnect is called from a different task than connect. In this case,
        we just clear references and let GC handle cleanup.
        """
        # Clear session first
        session_ctx = self._session_context
        self._session_context = None
        self.session = None

        streams_ctx = self._streams_context
        self._streams_context = None

        # Try to properly close contexts, but don't fail if task boundary issues
        try:
            if session_ctx:
                await session_ctx.__aexit__(None, None, None)
        except (RuntimeError, GeneratorExit, BaseException):
            pass  # Task boundary issue or cleanup error - GC will handle

        try:
            if streams_ctx:
                await streams_ctx.__aexit__(None, None, None)
        except (RuntimeError, GeneratorExit, BaseException):
            pass  # Task boundary issue or cleanup error - GC will handle

        logger.debug(f"Disconnected from MCP server: {self.mcp_server.name}")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
