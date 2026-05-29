"""MCP Client for connecting to and executing HTTP-based MCP servers."""

import asyncio
from datetime import timedelta
from types import TracebackType
from typing import Any, Optional, cast

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from intric.main.config import get_settings
from intric.main.exceptions import MCPAuthenticationError, MCPClientError
from intric.main.logging import get_logger
from intric.mcp_servers.domain.entities.mcp_server import MCPServer

logger = get_logger(__name__)

_settings = get_settings()
MCP_CONNECTION_TIMEOUT_DEFAULT = _settings.mcp_client_connect_timeout_seconds
MCP_LIST_TOOLS_TIMEOUT_DEFAULT = _settings.mcp_client_list_tools_timeout_seconds
MCP_TOOL_CALL_TIMEOUT_DEFAULT = _settings.mcp_client_call_timeout_seconds

# Defensive caps for resource content blocks. An adversarial MCP server can
# emit arbitrarily large `text` / `_meta` payloads. Cap the parsed resource
# blocks before they flow into persistence or citation rendering.
RESOURCE_TEXT_MAX_BYTES = 8 * 1024
RESOURCE_META_MAX_BYTES = 16 * 1024


def _truncate_text(value: Optional[str], max_bytes: int) -> Optional[str]:
    if value is None:
        return None
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _truncate_meta(meta: Any, max_bytes: int) -> dict[str, Any]:
    """Best-effort cap on the JSON-serialized size of an MCP resource _meta dict.

    Keeps the structure (returns a dict) but drops keys from the tail until the
    JSON payload fits. Non-dict input collapses to an empty dict.
    """
    import json

    if not isinstance(meta, dict):
        return {}
    typed_meta = cast(dict[str, Any], meta)
    if len(json.dumps(typed_meta).encode("utf-8")) <= max_bytes:
        return typed_meta
    truncated: dict[str, Any] = {}
    for k, v in typed_meta.items():
        candidate: dict[str, Any] = {**truncated, k: v}
        if len(json.dumps(candidate).encode("utf-8")) > max_bytes:
            break
        truncated = candidate
    return truncated


def _extract_error_message(exc: BaseException) -> str:
    """Extract meaningful error message from exception groups.

    The MCP library uses anyio TaskGroups which wrap errors in
    BaseExceptionGroup. This extracts the actual HTTP/connection
    error, ignoring noise like GeneratorExit and cancel scope errors.
    """
    if isinstance(exc, BaseExceptionGroup):
        sub_exceptions: tuple[BaseException, ...] = exc.exceptions  # type: ignore
        for sub_exc in sub_exceptions:
            msg = _extract_error_message(sub_exc)
            if msg:
                return msg
        return str(exc)  # type: ignore

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
                return (
                    "Authentication failed (401 Unauthorized). Check your bearer token."
                )
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
        list_tools_timeout: int | None = None,
        tool_call_timeout: int | None = None,
        resume_mcp_session_id: str | None = None,
    ):
        """
        Initialize MCP client.

        Args:
            mcp_server: MCP server configuration
            auth_credentials: Authentication credentials from tenant settings
            timeout: Connection timeout in seconds (defaults to 30s)
            resume_mcp_session_id: If set, sent as the initial ``Mcp-Session-Id``
                header so the server resumes the prior logical session for state
                that outlives a single transport connection.
        """
        super().__init__()
        self.mcp_server = mcp_server
        self.auth_credentials = auth_credentials or {}
        self.timeout = timeout or MCP_CONNECTION_TIMEOUT_DEFAULT
        self.list_tools_timeout = list_tools_timeout or MCP_LIST_TOOLS_TIMEOUT_DEFAULT
        self.tool_call_timeout = tool_call_timeout or MCP_TOOL_CALL_TIMEOUT_DEFAULT
        self.resume_mcp_session_id = resume_mcp_session_id
        self.session: Optional[ClientSession] = None
        self._streams_context = None
        self._session_context = None
        # Populated after a successful connect() / initialize() round-trip.
        # assigned_mcp_session_id is the MCP-protocol session id the server
        # returned and we should persist.
        self.server_info_name: Optional[str] = None
        self.server_info_version: Optional[str] = None
        self.assigned_mcp_session_id: Optional[str] = None
        # Set by the streamable HTTP transport; reading it after initialize()
        # returns the session id the SDK captured from the server response.
        self._get_session_id_callable: Optional[Any] = None

    async def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication + session-resume headers for this connection.

        ``Mcp-Session-Id`` is the MCP-protocol session id. Sending a previously
        stored value asks the server to resume that logical session — the SDK
        will then propagate the server's response value (which may be the same
        or a fresh one) on every subsequent request automatically.

        """
        headers: dict[str, str] = {}

        token: Optional[str] = None
        if self.mcp_server.http_auth_type == "bearer":
            token = self.auth_credentials.get("token")

        if token:
            headers["Authorization"] = f"Bearer {token}"

        if self.resume_mcp_session_id:
            headers["Mcp-Session-Id"] = self.resume_mcp_session_id

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
                try:
                    diagnostic_headers = await self._build_auth_headers()
                except Exception:
                    # Still produce a diagnostic if auth header construction
                    # fails for any unexpected reason.
                    diagnostic_headers = {}
                error_msg = await _diagnose_http(
                    self.mcp_server.http_url, diagnostic_headers
                )
            logger.error(
                f"Failed to connect to MCP server {self.mcp_server.name}: {error_msg}"
            )
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

        Two flavors:
          1. Fresh connect (no resume_mcp_session_id): open transport, run
             ``initialize()``, capture the server-assigned session id.
          2. Resume (resume_mcp_session_id set): open transport with
             ``terminate_on_close=False`` so the previous turn's DELETE didn't
             evict the server-side session, pre-seed the SDK transport's
             session_id with the persisted value, and SKIP ``initialize()``.
             Calling ``initialize()`` on resume can cause some servers to mint
             a fresh Mcp-Session-Id and lose per-session state. See the
             cross-turn contract in ``ChatSessionMcpStateRepo``.
        """
        headers = await self._build_auth_headers()

        # terminate_on_close=False: the SDK otherwise sends DELETE /mcp on
        # transport teardown, which evicts the server-side session and breaks
        # the next turn's resume. Server idle TTL bounds the leak.
        streams_context = streamablehttp_client(
            url=self.mcp_server.http_url,
            headers=headers,
            timeout=timedelta(seconds=self.timeout),
            terminate_on_close=False,
        )

        streams = await streams_context.__aenter__()

        self._streams_context = streams_context
        read, write, get_session_id = streams
        # ``get_session_id`` is the bound ``transport.get_session_id`` method;
        # its ``__self__`` is the StreamableHTTPTransport instance, which is
        # the only handle we have on the transport's session_id field (the
        # outer ``streamablehttp_client`` async generator does not expose it
        # directly). Pre-seeding session_id is required for resume — see the
        # docstring.
        self._get_session_id_callable = get_session_id
        transport = getattr(get_session_id, "__self__", None)
        if transport is None:
            await streams_context.__aexit__(None, None, None)
            self._streams_context = None
            raise MCPClientError(
                "MCP SDK transport not accessible — get_session_id is not a "
                "bound method. The SDK version may be incompatible with eneo's "
                "cross-turn resume mechanism."
            )
        logger.debug(
            f"Streamable HTTP transport connected to {self.mcp_server.http_url}"
        )

        session_context = ClientSession(read, write)
        try:
            session = await session_context.__aenter__()
        except BaseException:
            try:
                await streams_context.__aexit__(None, None, None)
            except BaseException:
                pass
            self._streams_context = None
            raise

        self._session_context = session_context
        self.session = session

        if self.resume_mcp_session_id:
            # Resume path: pre-seed the SDK's session_id so every outgoing
            # request carries the persisted Mcp-Session-Id, and DO NOT call
            # initialize(). serverInfo/protocol_version stay None on this
            # transport — that's fine because the server negotiated them on
            # the original turn for this logical session, and the SDK only
            # sends MCP-Protocol-Version when it has a value (skipping is
            # acceptable for a resumed session).
            transport.session_id = self.resume_mcp_session_id
            self.assigned_mcp_session_id = self.resume_mcp_session_id
            logger.info(
                "Resumed MCP session for %s (session_id=%s, skipped initialize)",
                self.mcp_server.name,
                self.resume_mcp_session_id,
            )
            return

        # Fresh-connect path: negotiate via initialize() and capture the
        # server-assigned session id.
        try:
            init_result = await self.session.initialize()
        except BaseException:
            await self._cleanup_contexts()
            raise

        try:
            server_info = init_result.serverInfo
            self.server_info_name = getattr(server_info, "name", None)
            self.server_info_version = getattr(server_info, "version", None)
        except AttributeError:
            # Pre-spec servers may omit serverInfo; not a fatal error.
            pass

        try:
            self.assigned_mcp_session_id = get_session_id()
        except Exception:
            self.assigned_mcp_session_id = None

        logger.info(
            "Connected to MCP server: %s (server_info=%s/%s, session_id=%s)",
            self.mcp_server.name,
            self.server_info_name,
            self.server_info_version,
            self.assigned_mcp_session_id,
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        """
        List all available tools from the MCP server.

        Returns:
            List of tool definitions
        """
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        try:
            response = await asyncio.wait_for(
                self.session.list_tools(),
                timeout=self.list_tools_timeout,
            )
            tools: list[dict[str, Any]] = []

            for tool in response.tools:
                annotations = getattr(tool, "annotations", None)
                title = getattr(annotations, "title", None) or getattr(
                    tool, "title", None
                )
                tools.append(
                    {
                        "name": tool.name,
                        "title": title,
                        "description": tool.description,
                        "input_schema": tool.inputSchema,
                    }
                )

            logger.debug(f"Listed {len(tools)} tools from {self.mcp_server.name}")
            return tools

        except asyncio.TimeoutError as e:
            raise MCPClientError(
                f"Failed to list tools: request timed out after {self.list_tools_timeout}s"
            ) from e
        except MCPClientError:
            raise
        except BaseException as e:
            error_msg = _extract_error_message(e) or str(e)
            lowered = error_msg.lower()
            if any(
                x in lowered
                for x in ("401", "403", "unauthorized", "forbidden", "authentication")
            ):
                raise MCPAuthenticationError(
                    f"Failed to list tools: {error_msg}"
                ) from e
            logger.error(
                f"Failed to list tools from {self.mcp_server.name}: {error_msg}"
            )
            raise MCPClientError(f"Failed to list tools: {error_msg}") from e

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
            response = await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments=arguments),
                timeout=self.tool_call_timeout,
            )

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
                    # The MCP SDK wraps the resource in an `EmbeddedResource`
                    # whose `.resource` is `TextResourceContents | BlobResourceContents`.
                    # Older shapes flatten the fields onto the content item;
                    # probe both so we work across SDK versions.
                    resource = getattr(content_item, "resource", content_item)
                    raw_meta: Any = (
                        getattr(resource, "_meta", None)
                        or getattr(resource, "meta", None)
                        or {}
                    )
                    raw_uri = getattr(resource, "uri", None)
                    # Pydantic AnyUrl on the SDK side; asyncpg won't coerce it,
                    # and downstream consumers expect a plain string.
                    uri_str = str(raw_uri) if raw_uri is not None else None
                    content_list.append(
                        {
                            "type": "resource",
                            "uri": uri_str,
                            "text": _truncate_text(
                                getattr(resource, "text", None),
                                RESOURCE_TEXT_MAX_BYTES,
                            ),
                            "mime_type": getattr(resource, "mimeType", None),
                            "meta": _truncate_meta(raw_meta, RESOURCE_META_MAX_BYTES),
                        }
                    )

            result: dict[str, Any] = {
                "content": content_list,
                "is_error": bool(response.isError),
            }

            logger.info(f"Called tool {tool_name} on {self.mcp_server.name}")
            return result

        except asyncio.TimeoutError as e:
            raise MCPClientError(
                f"Tool call failed: request timed out after {self.tool_call_timeout}s"
            ) from e
        except MCPClientError:
            raise
        except BaseException as e:
            error_msg = _extract_error_message(e) or str(e)
            lowered = error_msg.lower()
            if any(
                x in lowered
                for x in ("401", "403", "unauthorized", "forbidden", "authentication")
            ):
                raise MCPAuthenticationError(f"Tool call failed: {error_msg}") from e
            logger.error(
                f"Failed to call tool {tool_name} on {self.mcp_server.name}: {error_msg}"
            )
            raise MCPClientError(f"Tool call failed: {error_msg}") from e

    async def disconnect(self) -> None:
        """Disconnect from the MCP server.

        Must run on the same asyncio.Task that called connect(). The MCP SDK's
        streamablehttp_client uses anyio cancel scopes bound to the entering
        task; calling __aexit__ from a different task fails the task-boundary
        check and leaks the internal anyio TaskGroup's child tasks (the
        persistent HTTP read/write loops). We log this case explicitly so
        leaks are visible rather than disguised as a slow CPU climb.
        """
        # Clear session first
        session_ctx = self._session_context
        self._session_context = None
        self.session = None

        streams_ctx = self._streams_context
        self._streams_context = None

        cleanup_errors: list[BaseException] = []

        try:
            if session_ctx:
                await session_ctx.__aexit__(None, None, None)
        except BaseException as e:
            cleanup_errors.append(e)

        try:
            if streams_ctx:
                await streams_ctx.__aexit__(None, None, None)
        except BaseException as e:
            cleanup_errors.append(e)

        for err in cleanup_errors:
            msg = str(err).lower()
            if "cancel scope" in msg or "different task" in msg:
                logger.error(
                    "MCP cleanup task-boundary error for %s: %s. This leaks the "
                    "streamablehttp_client TaskGroup; ensure connect() and "
                    "disconnect() run on the same asyncio.Task.",
                    self.mcp_server.name,
                    err,
                )
            else:
                logger.warning(
                    "MCP cleanup error for %s: %s", self.mcp_server.name, err
                )

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
