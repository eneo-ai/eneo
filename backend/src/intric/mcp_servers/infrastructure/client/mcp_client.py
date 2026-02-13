"""MCP Client for connecting to and executing HTTP-based MCP servers."""

import asyncio
import base64
import time
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

# Buffer before token expiry to trigger refresh (seconds)
_TOKEN_EXPIRY_BUFFER = 30


class MCPClientError(Exception):
    """Base exception for MCP client errors."""

    pass


class MCPClient:
    """Client for interacting with HTTP-based MCP servers."""

    # Process-wide OAuth2 token cache: cache_key -> (access_token, expires_at_timestamp)
    _token_cache: dict[str, tuple[str, float]] = {}
    _token_locks: dict[str, asyncio.Lock] = {}
    _token_locks_guard = asyncio.Lock()

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
        self._resolved_bearer_token: str | None = None

    @classmethod
    async def _get_token_lock(cls, cache_key: str) -> asyncio.Lock:
        async with cls._token_locks_guard:
            lock = cls._token_locks.get(cache_key)
            if lock is None:
                lock = asyncio.Lock()
                cls._token_locks[cache_key] = lock
            return lock

    async def _acquire_oauth_token(self) -> str:
        """Acquire an OAuth2 access token using client credentials grant.

        Uses HTTP Basic auth with client_id:client_secret to the token endpoint.
        Tokens are cached process-wide and reused until near expiry.

        Returns:
            Access token string

        Raises:
            MCPClientError: If token acquisition fails
        """
        token_url = self.auth_credentials.get("token_url")
        client_id = self.auth_credentials.get("client_id")
        client_secret = self.auth_credentials.get("client_secret")
        scope = self.auth_credentials.get("scope")

        if not token_url or not client_id or not client_secret:
            raise MCPClientError(
                "OAuth2 client credentials requires token_url, client_id, and client_secret"
            )

        cache_key = f"{token_url}:{client_id}"
        lock = await self._get_token_lock(cache_key)

        async with lock:
            # Check cache
            cached = self._token_cache.get(cache_key)
            if cached:
                token, expires_at = cached
                if time.time() < expires_at - _TOKEN_EXPIRY_BUFFER:
                    logger.debug(
                        f"Using cached OAuth2 token for {self.mcp_server.name}"
                    )
                    return token

            # Fetch new token
            logger.info(
                f"Acquiring OAuth2 token for {self.mcp_server.name} from {token_url}"
            )

            basic_auth = base64.b64encode(
                f"{client_id}:{client_secret}".encode()
            ).decode()

            data: dict[str, str] = {"grant_type": "client_credentials"}
            if scope:
                data["scope"] = scope

            try:
                async with httpx.AsyncClient() as http_client:
                    response = await http_client.post(
                        token_url,
                        data=data,
                        headers={
                            "Authorization": f"Basic {basic_auth}",
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        timeout=10,
                    )
                    response.raise_for_status()
                    token_data = response.json()
            except httpx.HTTPStatusError as e:
                raise MCPClientError(
                    f"OAuth2 token request failed with status {e.response.status_code}: "
                    f"{e.response.text}"
                )
            except Exception as e:
                raise MCPClientError(f"OAuth2 token request failed: {e}")

            access_token = token_data.get("access_token")
            if not access_token:
                raise MCPClientError("OAuth2 token response missing access_token")

            # Cache with expiry (default 1 hour if not provided)
            expires_in = token_data.get("expires_in", 3600)
            expires_at = time.time() + expires_in
            self._token_cache[cache_key] = (access_token, expires_at)

            logger.info(
                f"Acquired OAuth2 token for {self.mcp_server.name} "
                f"(expires in {expires_in}s)"
            )
            return access_token

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers based on server auth type."""
        headers: dict[str, str] = {}

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

        elif self.mcp_server.http_auth_type == "oauth2_client_credentials":
            if self._resolved_bearer_token:
                headers["Authorization"] = f"Bearer {self._resolved_bearer_token}"

        return headers

    async def connect(self) -> None:
        """Connect to the HTTP-based MCP server."""
        try:
            await asyncio.wait_for(self._connect_internal(), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.error(
                f"Connection to MCP server {self.mcp_server.name} timed out after {self.timeout}s"
            )
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
        # For OAuth2 client credentials, acquire token before building headers
        if self.mcp_server.http_auth_type == "oauth2_client_credentials":
            self._resolved_bearer_token = await self._acquire_oauth_token()

        headers = self._build_auth_headers()

        # Create the streamable HTTP context manager
        streams_context = streamablehttp_client(
            url=self.mcp_server.http_url, headers=headers
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
            tools: list[dict[str, Any]] = []

            for tool in response.tools:
                tool_def: dict[str, Any] = {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                # Capture _meta from tool definition (MCP Apps standard)
                if hasattr(tool, "meta") and tool.meta:
                    tool_def["meta"] = tool.meta
                tools.append(tool_def)

            logger.debug(f"Listed {len(tools)} tools from {self.mcp_server.name}")
            return tools

        except Exception as e:
            logger.error(f"Failed to list tools from {self.mcp_server.name}: {e}")
            raise MCPClientError(f"Failed to list tools: {e}")

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
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
                    content_list.append(
                        {
                            "type": "text",
                            "text": content_item.text,
                        }
                    )
                elif content_item.type == "image":
                    content_list.append(
                        {
                            "type": "image",
                            "data": content_item.data,
                            "mime_type": content_item.mimeType,
                        }
                    )
                elif content_item.type == "resource":
                    content_list.append(
                        {
                            "type": "resource",
                            "uri": getattr(content_item, "uri", None),
                            "text": getattr(content_item, "text", None),
                        }
                    )

            result: dict[str, Any] = {
                "content": content_list,
                "is_error": bool(response.isError),
            }

            # Preserve _meta from tool result (used by MCP Apps for UI data)
            if hasattr(response, "meta") and response.meta:
                result["_meta"] = response.meta

            logger.info(f"Called tool {tool_name} on {self.mcp_server.name}")
            return result

        except Exception as e:
            logger.error(
                f"Failed to call tool {tool_name} on {self.mcp_server.name}: {e}"
            )
            raise MCPClientError(f"Tool call failed: {e}")

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """
        Read a resource from the MCP server.

        Args:
            uri: Resource URI (e.g., "ui://infocaption/guide-viewer")

        Returns:
            Dict with "content" (string) and "mime_type"
        """
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        try:
            response = await self.session.read_resource(uri)

            # Return first content item
            for content_item in response.contents:
                text = getattr(content_item, "text", None)
                mime_type = getattr(content_item, "mimeType", "text/html")
                if text is not None:
                    return {"content": text, "mime_type": mime_type}

            return {"content": "", "mime_type": "text/html"}

        except Exception as e:
            logger.error(
                f"Failed to read resource {uri} from {self.mcp_server.name}: {e}"
            )
            raise MCPClientError(f"Resource read failed: {e}")

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

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.disconnect()
