"""MCP Client for connecting to and executing HTTP-based MCP servers."""

import asyncio
from datetime import timedelta
from types import TracebackType
from typing import Any, Callable, Optional, cast

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import ServerNotification, ToolListChangedNotification

from eneo.main.config import get_settings
from eneo.main.exceptions import MCPAuthenticationError, MCPClientError
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = get_logger(__name__)

_settings = get_settings()
MCP_CONNECTION_TIMEOUT_DEFAULT = _settings.mcp_client_connect_timeout_seconds
MCP_LIST_TOOLS_TIMEOUT_DEFAULT = _settings.mcp_client_list_tools_timeout_seconds
MCP_TOOL_CALL_TIMEOUT_DEFAULT = _settings.mcp_client_call_timeout_seconds
MCP_TERMINATE_TIMEOUT_SECONDS = 5.0

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


def _is_session_not_found(exc: BaseException) -> bool:
    """True when an error means the server no longer knows our session id.

    Per the MCP streamable-HTTP transport, a request bearing an unknown
    ``Mcp-Session-Id`` is answered with HTTP 404 and the client is expected to
    start a fresh session. We treat only this definitive signal as grounds to
    abandon a resumed (sticky) session: transient errors must NOT, or we would
    orphan per-session server state such as a user's attached files.
    """
    msg = (_extract_error_message(exc) or str(exc)).lower()
    return (
        "404" in msg
        or "session not found" in msg
        or "no valid session" in msg
        or "session has been terminated" in msg
        or "invalid session id" in msg
    )


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
        on_tools_list_changed: Callable[[], None] | None = None,
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
            on_tools_list_changed: Fired (best-effort) when the server pushes a
                ``notifications/tools/list_changed``. Progressive-discovery
                servers emit this after a tool like ``load_tools`` activates new
                tools; the proxy reacts by re-listing so the freshly activated
                tools become callable on the next model turn.
        """
        super().__init__()
        self.mcp_server = mcp_server
        self.auth_credentials = auth_credentials or {}
        self.timeout = timeout or MCP_CONNECTION_TIMEOUT_DEFAULT
        self.list_tools_timeout = list_tools_timeout or MCP_LIST_TOOLS_TIMEOUT_DEFAULT
        self.tool_call_timeout = tool_call_timeout or MCP_TOOL_CALL_TIMEOUT_DEFAULT
        self.resume_mcp_session_id = resume_mcp_session_id
        self._on_tools_list_changed = on_tools_list_changed
        # Set when a tools/list_changed notification arrives on this session.
        # The proxy also re-lists the servers it just called, so this flag is a
        # protocol-correct optimization rather than the sole trigger.
        self.tools_list_changed_pending: bool = False
        # Captured from the initialize() handshake (fresh connect only). Default
        # False — including resumed sessions, which skip initialize; those rely
        # on the dirty flag above, set by the actual notification, instead.
        self.supports_tools_list_changed: bool = False
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

    async def _handle_session_message(self, message: Any) -> None:
        """ClientSession message handler.

        We only care about ``notifications/tools/list_changed``: it tells us the
        server's advertised tool set just changed (progressive discovery), so the
        next model turn must see the new tools. Everything else mirrors the SDK's
        default handler (a cooperative checkpoint). Never raises — a handler
        exception would tear down the session's receive loop.
        """
        try:
            if isinstance(message, ServerNotification) and isinstance(
                message.root, ToolListChangedNotification
            ):
                self.tools_list_changed_pending = True
                if self._on_tools_list_changed is not None:
                    self._on_tools_list_changed()
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Error handling MCP notification from %s", self.mcp_server.name
            )
        finally:
            await asyncio.sleep(0)

    async def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers for this connection.

        This intentionally does NOT set ``Mcp-Session-Id``. Session resume is
        carried solely by seeding the SDK transport's ``session_id`` field (see
        ``_connect_internal``), which the SDK then sends on every request and
        keeps in sync with the server's response value.

        Setting the header here as well would duplicate it: the dict passed to
        ``streamablehttp_client`` becomes both the httpx client's default
        headers and the per-request base, and the SDK independently re-adds
        ``mcp-session-id`` from ``session_id``. httpx then folds the two copies
        into a single comma-joined value (``id, id``), which servers validating
        the session-id shape reject with HTTP 400.
        """
        headers: dict[str, str] = {}

        token: Optional[str] = None
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

        session_context = ClientSession(
            read, write, message_handler=self._handle_session_message
        )
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
            # request carries the persisted Mcp-Session-Id exactly once (the
            # SDK adds it from session_id; we must NOT also pass it in the
            # headers dict, or httpx folds the two copies into one rejected
            # comma-joined value). DO NOT call initialize() —
            # serverInfo/protocol_version stay None on this
            # transport — that's fine because the server negotiated them on
            # the original turn for this logical session, and the SDK only
            # sends MCP-Protocol-Version when it has a value (skipping is
            # acceptable for a resumed session).
            transport.session_id = self.resume_mcp_session_id
            self.assigned_mcp_session_id = self.resume_mcp_session_id

            # Validate the resumed session before handing it back. We keep one
            # logical Mcp-Session-Id across turns so server-side per-session
            # state — notably files a user attached on an earlier turn
            # (file-workbench MCP) — stays reachable. If the server restarted,
            # redeployed, or evicted this idle session, the id is dead (HTTP 404
            # per the streamable-HTTP spec) and that state is already gone, so
            # mint a fresh session. Reconnect fresh ONLY on that definitive
            # signal: a transient error must keep the sticky id, or we would
            # orphan a still-valid session and its attached files.
            try:
                await self.session.send_ping()
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:
                if _is_session_not_found(exc):
                    logger.warning(
                        "Resumed MCP session for %s is gone server-side "
                        "(session_id=%s); dropping the dead id and reconnecting "
                        "fresh: %s",
                        self.mcp_server.name,
                        self.resume_mcp_session_id,
                        _extract_error_message(exc) or exc,
                    )
                    await self._cleanup_contexts()
                    self.resume_mcp_session_id = None
                    self.assigned_mcp_session_id = None
                    # resume_mcp_session_id is now None, so this takes the
                    # fresh-connect path and the proxy persists the new id.
                    await self._connect_internal()
                    return
                # Transient or ambiguous failure: keep the sticky session id and
                # proceed. The session is probably still valid, and real tool
                # calls carry their own error handling.
                logger.info(
                    "Ping on resumed MCP session for %s failed transiently; "
                    "keeping sticky session_id=%s: %s",
                    self.mcp_server.name,
                    self.resume_mcp_session_id,
                    _extract_error_message(exc) or exc,
                )
                return

            logger.info(
                "Resumed MCP session for %s (session_id=%s, validated, "
                "skipped initialize)",
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

        # Whether this server advertised tools.listChanged. Only servers that
        # opt in get re-listed by the proxy's belt-and-suspenders path; static
        # servers keep their original DB-synced tool set untouched (no extra
        # tools/list round-trip, no exposure of un-synced server-side tools).
        try:
            tools_cap = getattr(init_result.capabilities, "tools", None)
            self.supports_tools_list_changed = bool(
                getattr(tools_cap, "listChanged", False)
            )
        except Exception:
            self.supports_tools_list_changed = False

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
                elif content_item.type == "resource_link":
                    # Typed resource reference (MCP spec, 2025-11-25): a URL plus
                    # mimeType, no embedded bytes. `annotations.audience` marks
                    # who the block is for; downstream gates display on it.
                    annotations = getattr(content_item, "annotations", None)
                    audience = (
                        getattr(annotations, "audience", None) if annotations else None
                    )
                    raw_uri = getattr(content_item, "uri", None)
                    content_list.append(
                        {
                            "type": "resource_link",
                            "uri": str(raw_uri) if raw_uri is not None else None,
                            "mime_type": getattr(content_item, "mimeType", None),
                            "meta": _truncate_meta(
                                getattr(content_item, "_meta", None) or {},
                                RESOURCE_META_MAX_BYTES,
                            ),
                            # Normalize the Role enum to plain strings;
                            # None == "no audience stated".
                            "audience": [str(a) for a in audience]
                            if audience
                            else None,
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

    async def terminate_protocol_session(self, mcp_session_id: str) -> None:
        """Terminate a persisted server-side MCP session.

        Transport teardown keeps protocol sessions alive so later chat turns
        can resume them. Conversation deletion must therefore explicitly send
        HTTP DELETE with the persisted ``Mcp-Session-Id``. HTTP 404 is treated
        as idempotent success because the server has already forgotten it.
        """
        headers = await self._build_auth_headers()
        headers["Mcp-Session-Id"] = mcp_session_id

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(MCP_TERMINATE_TIMEOUT_SECONDS)
        ) as client:
            response = await client.delete(self.mcp_server.http_url, headers=headers)

        if response.status_code in {404, 405}:
            return
        response.raise_for_status()

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
