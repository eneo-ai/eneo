"""MCP Client for connecting to and executing HTTP-based MCP servers."""

from datetime import timedelta
from types import TracebackType
from typing import Any, Optional

import httpx
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


def _extract_error_message(exc: BaseException) -> str:
    """Extract meaningful error message from exception groups.

    The MCP library uses anyio TaskGroups which wrap errors in
    BaseExceptionGroup. This extracts the actual HTTP/connection
    error, ignoring noise like GeneratorExit and cancel scope errors.
    """
    if isinstance(exc, BaseExceptionGroup):
        for sub_exc in exc.exceptions:
            msg = _extract_error_message(sub_exc)
            if msg:
                return msg
        return str(exc)

    # Skip noise exceptions
    if isinstance(exc, (GeneratorExit, KeyboardInterrupt, SystemExit)):
        return ""
    if "cancel scope" in str(exc).lower():
        return ""

    return str(exc)


async def _diagnose_http(url: str, headers: dict[str, str]) -> str:
    """Quick HTTP request to diagnose the real error when MCP protocol fails.

    The MCP library's anyio TaskGroups can swallow the actual HTTP error
    (e.g. 401) and replace it with a cancel scope error. This makes a
    direct HTTP request to surface the real issue.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "eneo", "version": "0.1"},
                    },
                },
            )
            if resp.status_code == 401:
                return "Authentication failed (401 Unauthorized). Check your bearer token."
            elif resp.status_code == 403:
                return "Access denied (403 Forbidden). Check your credentials."
            elif resp.status_code >= 500:
                return f"Server error (HTTP {resp.status_code})."
            elif resp.status_code >= 400:
                return f"Server returned HTTP {resp.status_code}."
    except httpx.ConnectError:
        return f"Could not connect to {url}. Verify the URL and that the server is running."
    except httpx.TimeoutException:
        return f"Connection to {url} timed out."
    except Exception:
        pass
    return "Connection failed for unknown reasons."


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
        headers: dict[str, str] = {}

        if self.mcp_server.http_auth_type == "bearer":
            token = self.auth_credentials.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"

        return headers

    async def connect(self) -> None:
        """Connect to the HTTP-based MCP server.

        Timeout is delegated to the HTTP transport (not asyncio.wait_for)
        to avoid conflicts with anyio's cancel scopes in the MCP library.
        """
        try:
            await self._connect_internal()
        except MCPClientError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as e:
            error_msg = _extract_error_message(e)
            if not error_msg:
                # Cancel scope or other unhelpful error — do a direct HTTP
                # request to surface the real issue (e.g. 401).
                error_msg = await _diagnose_http(
                    self.mcp_server.http_url, self._build_auth_headers()
                )
            logger.error(f"Failed to connect to MCP server {self.mcp_server.name}: {error_msg}")
            await self._cleanup_contexts()
            raise MCPClientError(error_msg) from e

    async def _cleanup_contexts(self) -> None:
        """Clean up any partially initialized contexts."""
        try:
            if self._session_context:
                await self._session_context.__aexit__(None, None, None)
        except BaseException:
            pass
        finally:
            self._session_context = None
            self.session = None

        try:
            if self._streams_context:
                await self._streams_context.__aexit__(None, None, None)
        except BaseException:
            pass
        finally:
            self._streams_context = None

    async def _connect_internal(self) -> None:
        """Internal connection logic.

        Errors are NOT wrapped here — they propagate to connect() which
        has the diagnostic fallback for unhelpful cancel scope errors.
        """
        headers = self._build_auth_headers()

        # Create the streamable HTTP context manager with timeout delegated
        # to the transport layer (avoids asyncio.wait_for vs anyio conflicts)
        streams_context = streamablehttp_client(
            url=self.mcp_server.http_url,
            headers=headers,
            timeout=timedelta(seconds=self.timeout),
        )

        # Enter the streams context
        streams = await streams_context.__aenter__()

        # Successfully entered - now save the reference
        self._streams_context = streams_context
        read, write, get_session_id = streams
        logger.debug(f"Streamable HTTP transport connected to {self.mcp_server.http_url}")

        # Create and enter session context
        session_context = ClientSession(read, write)
        try:
            session = await session_context.__aenter__()
        except BaseException:
            # Session entry failed - cleanup streams context
            try:
                await streams_context.__aexit__(None, None, None)
            except BaseException:
                pass
            self._streams_context = None
            raise

        # Successfully entered - save references
        self._session_context = session_context
        self.session = session

        # Initialize the MCP protocol session
        try:
            await self.session.initialize()
        except BaseException:
            await self._cleanup_contexts()
            raise

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
            tools: list[dict[str, Any]] = []

            for tool in response.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                })

            logger.debug(f"Listed {len(tools)} tools from {self.mcp_server.name}")
            return tools

        except MCPClientError:
            raise
        except BaseException as e:
            error_msg = _extract_error_message(e) or str(e)
            logger.error(f"Failed to list tools from {self.mcp_server.name}: {error_msg}")
            raise MCPClientError(f"Failed to list tools: {error_msg}") from e

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
            content_list: list[dict[str, Any]] = []

            for content_item in response.content:
                if content_item.type == "text":
                    content_list.append({
                        "type": "text",
                        "text": content_item.text,
                    })
                elif content_item.type == "image":
                    content_list.append({
                        "type": "image",
                        "data": content_item.data,
                        "mime_type": content_item.mimeType,
                    })
                elif content_item.type == "resource":
                    content_list.append({
                        "type": "resource",
                        "uri": getattr(content_item, "uri", None),
                        "text": getattr(content_item, "text", None),
                    })

            result: dict[str, Any] = {
                "content": content_list,
                "is_error": bool(response.isError),
            }

            logger.info(f"Called tool {tool_name} on {self.mcp_server.name}")
            return result

        except MCPClientError:
            raise
        except BaseException as e:
            error_msg = _extract_error_message(e) or str(e)
            logger.error(f"Failed to call tool {tool_name} on {self.mcp_server.name}: {error_msg}")
            raise MCPClientError(f"Tool call failed: {error_msg}") from e

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
        except BaseException:
            pass  # Task boundary issue or cleanup error - GC will handle

        try:
            if streams_ctx:
                await streams_ctx.__aexit__(None, None, None)
        except BaseException:
            pass  # Task boundary issue or cleanup error - GC will handle

        logger.debug(f"Disconnected from MCP server: {self.mcp_server.name}")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.disconnect()
