"""MCP Client for connecting to and executing HTTP-based MCP servers."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, AsyncContextManager, Callable, Optional, cast

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import ClientSession
from mcp.client.streamable_http import (
    GetSessionIdCallback,
    streamable_http_client,
)
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.message import SessionMessage
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ServerNotification,
    ToolListChangedNotification,
)

from eneo.main.config import get_settings
from eneo.main.exceptions import MCPAuthenticationError, MCPClientError
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = get_logger(__name__)

_settings = get_settings()
MCP_CONNECTION_TIMEOUT_DEFAULT = _settings.mcp_client_connect_timeout_seconds
MCP_LIST_TOOLS_TIMEOUT_DEFAULT = _settings.mcp_client_list_tools_timeout_seconds
MCP_TOOL_CALL_TIMEOUT_DEFAULT = _settings.mcp_client_call_timeout_seconds
MCP_TOOL_LIST_PROTOCOL_OVERHEAD_BYTES = 64 * 1024
MCP_INITIALIZE_RESPONSE_MAX_BYTES = 1024 * 1024
MCP_DELETE_RESPONSE_MAX_BYTES = 64 * 1024

# Defensive caps for resource content blocks. An adversarial MCP server can
# emit arbitrarily large `text` / `_meta` payloads. Cap the parsed resource
# blocks before they flow into persistence or citation rendering.
RESOURCE_TEXT_MAX_BYTES = 8 * 1024
RESOURCE_META_MAX_BYTES = 16 * 1024
MCP_SSE_READ_TIMEOUT_SECONDS = 300.0

MCPStreams = tuple[
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
    GetSessionIdCallback,
]


def _skip_json_whitespace(data: bytes | bytearray | memoryview, offset: int) -> int:
    while offset < len(data) and data[offset] in b" \t\r\n":
        offset += 1
    return offset


def _skip_json_string(data: bytes | bytearray | memoryview, offset: int) -> int:
    if offset >= len(data) or data[offset] != ord('"'):
        return offset
    offset += 1
    while offset < len(data):
        current = data[offset]
        if current == ord("\\"):
            offset += 2
            continue
        offset += 1
        if current == ord('"'):
            return offset
    return offset


def _skip_json_value(data: bytes | bytearray | memoryview, offset: int) -> int:
    offset = _skip_json_whitespace(data, offset)
    if offset >= len(data):
        return offset
    if data[offset] == ord('"'):
        return _skip_json_string(data, offset)
    if data[offset] not in (ord("{"), ord("[")):
        while offset < len(data) and data[offset] not in b",]} \t\r\n":
            offset += 1
        return offset

    depth = 0
    while offset < len(data):
        current = data[offset]
        if current == ord('"'):
            offset = _skip_json_string(data, offset)
            continue
        if current in (ord("{"), ord("[")):
            depth += 1
        elif current in (ord("}"), ord("]")):
            depth -= 1
            if depth == 0:
                return offset + 1
        offset += 1
    return offset


def _json_key_matches(
    data: bytes | bytearray | memoryview,
    start: int,
    end: int,
    expected: str,
) -> bool:
    # Any ASCII key spelling equal to ``expected`` needs at most one six-byte
    # Unicode escape per character. Refuse larger keys without allocating.
    if end - start > 2 + (6 * len(expected)):
        return False
    try:
        decoded = json.loads(bytes(data[start:end]))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return decoded == expected


def _find_json_object_member(
    data: bytes | bytearray | memoryview,
    object_start: int,
    member_name: str,
) -> int | None:
    if object_start >= len(data) or data[object_start] != ord("{"):
        return None
    offset = object_start + 1
    matched_value_start: int | None = None
    while True:
        offset = _skip_json_whitespace(data, offset)
        if offset >= len(data) or data[offset] == ord("}"):
            return matched_value_start
        if data[offset] != ord('"'):
            return None
        key_start = offset
        key_end = _skip_json_string(data, offset)
        offset = _skip_json_whitespace(data, key_end)
        if offset >= len(data) or data[offset] != ord(":"):
            return None
        value_start = _skip_json_whitespace(data, offset + 1)
        if _json_key_matches(data, key_start, key_end, member_name):
            # JSON decoders retain the last duplicate object member. Keep
            # scanning so the pre-decode guard applies to the same value.
            matched_value_start = value_start
        offset = _skip_json_whitespace(data, _skip_json_value(data, value_start))
        if offset >= len(data) or data[offset] == ord("}"):
            return matched_value_start
        if data[offset] != ord(","):
            return None
        offset += 1


def _tools_list_exceeds_max_count(
    data: bytes | bytearray | memoryview, max_count: int
) -> bool:
    """Count direct ``result.tools`` elements without decoding definitions."""
    root_start = _skip_json_whitespace(data, 0)
    result_start = _find_json_object_member(data, root_start, "result")
    if result_start is None:
        return False
    tools_start = _find_json_object_member(data, result_start, "tools")
    if tools_start is None or data[tools_start] != ord("["):
        return False

    offset = _skip_json_whitespace(data, tools_start + 1)
    if offset < len(data) and data[offset] == ord("]"):
        return False
    count = 0
    while offset < len(data):
        count += 1
        if count > max_count:
            return True
        offset = _skip_json_whitespace(data, _skip_json_value(data, offset))
        if offset >= len(data) or data[offset] == ord("]"):
            return False
        if data[offset] != ord(","):
            return False
        offset = _skip_json_whitespace(data, offset + 1)
    return False


def _extract_sse_data(buffer: bytearray, event_end: int) -> bytearray | None:
    """Extract one complete SSE event's joined data fields."""
    read_offset = 0
    data = bytearray()
    found_data = False
    while read_offset < event_end:
        line_end = buffer.find(b"\n", read_offset, event_end)
        if line_end < 0:
            line_end = event_end
        content_end = (
            line_end - 1
            if line_end > read_offset and buffer[line_end - 1] == ord("\r")
            else line_end
        )
        if buffer.startswith(b"data:", read_offset, content_end):
            value_start = read_offset + len(b"data:")
            if value_start < content_end and buffer[value_start] == ord(" "):
                value_start += 1
            if found_data:
                data.append(ord("\n"))
            data.extend(memoryview(buffer)[value_start:content_end])
            found_data = True
        read_offset = line_end + 1
    return data if found_data else None


class _BoundedMCPResponseStream(httpx.AsyncByteStream):
    """Stop a bounded MCP response before the SDK can decode it."""

    def __init__(
        self,
        stream: httpx.AsyncByteStream,
        *,
        method: str,
        max_bytes: int,
        max_count: int | None,
        request_id: object,
        content_type: str,
        reject_immediately: bool = False,
    ) -> None:
        self._stream = stream
        self._method = method
        self._max_bytes = max_bytes
        self._max_count = max_count
        self._request_id = request_id
        self._is_sse = content_type.lower().startswith("text/event-stream")
        self._reject_immediately = reject_immediately

    def _error_response(self, message: str | None = None) -> bytes:
        if message is None:
            message = (
                f"MCP {self._method} wire response exceeds the configured "
                f"maximum of {self._max_bytes} bytes"
            )
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "error": {"code": -32000, "message": message},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if self._is_sse:
            return b"event: message\ndata: " + payload + b"\n\n"
        return payload

    async def __aiter__(self) -> AsyncGenerator[bytes]:
        buffered = bytearray()
        received_bytes = 0
        if self._reject_immediately:
            await self._stream.aclose()
            yield self._error_response()
            return

        async for chunk in self._stream:
            received_bytes += len(chunk)
            if received_bytes > self._max_bytes:
                await self._stream.aclose()
                yield self._error_response()
                return

            buffered.extend(chunk)
            if self._is_sse:
                # Hold each complete SSE event until it is known to be within
                # the ceiling. The SDK never receives an oversized JSON event.
                while True:
                    lf_delimiter = buffered.find(b"\n\n")
                    crlf_delimiter = buffered.find(b"\r\n\r\n")
                    candidates = [
                        (lf_delimiter, 2),
                        (crlf_delimiter, 4),
                    ]
                    candidates = [
                        candidate for candidate in candidates if candidate[0] >= 0
                    ]
                    if not candidates:
                        break
                    delimiter, delimiter_size = min(candidates)
                    event_end = delimiter + delimiter_size
                    event_data = _extract_sse_data(buffered, event_end)
                    if (
                        self._max_count is not None
                        and event_data is not None
                        and _tools_list_exceeds_max_count(event_data, self._max_count)
                    ):
                        await self._stream.aclose()
                        yield self._error_response(
                            "MCP tool catalog exceeds the configured maximum of "
                            f"{self._max_count} definitions"
                        )
                        return
                    yield bytes(memoryview(buffered)[:event_end])
                    del buffered[:event_end]

        if buffered:
            if (
                self._max_count is not None
                and not self._is_sse
                and _tools_list_exceeds_max_count(buffered, self._max_count)
            ):
                yield self._error_response(
                    "MCP tool catalog exceeds the configured maximum of "
                    f"{self._max_count} definitions"
                )
                return
            yield bytes(buffered)

    async def aclose(self) -> None:
        await self._stream.aclose()


def _json_rpc_request_payload(request: httpx.Request) -> dict[str, object] | None:
    try:
        payload: object = json.loads(request.content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, object], payload)


async def _bound_mcp_response(
    response: httpx.Response, *, tools_max_bytes: int, tools_max_count: int
) -> None:
    """Install method-specific pre-decode ceilings on untrusted MCP responses."""
    if response.request.method == "DELETE":
        # The SDK terminates a server-assigned session with a plain (buffering)
        # ``client.delete()`` on transport teardown and only reads the status
        # code, so cap the body an adversarial server could otherwise stream.
        if isinstance(response.stream, httpx.AsyncByteStream):
            response.stream = _BoundedMCPResponseStream(
                response.stream,
                method="DELETE",
                max_bytes=MCP_DELETE_RESPONSE_MAX_BYTES,
                max_count=None,
                request_id=None,
                content_type=response.headers.get("content-type", "application/json"),
            )
        return

    request_payload = _json_rpc_request_payload(response.request)
    if request_payload is None:
        return
    method = request_payload.get("method")
    if not isinstance(method, str):
        return
    if method == "tools/list":
        max_bytes = tools_max_bytes
        max_count: int | None = tools_max_count
    elif method == "initialize":
        max_bytes = MCP_INITIALIZE_RESPONSE_MAX_BYTES
        max_count = None
    else:
        return

    reject_immediately = False
    content_encoding = response.headers.get("content-encoding", "identity").lower()
    if content_encoding not in {"", "identity"}:
        # The stream ceiling counts bytes before HTTPX decoding. Requiring an
        # identity body prevents a small compressed response from expanding
        # beyond the configured bound during SDK JSON parsing.
        reject_immediately = True
        del response.headers["content-encoding"]

    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_bytes = int(content_length)
        except ValueError:
            declared_bytes = None
        if declared_bytes is not None and declared_bytes > max_bytes:
            reject_immediately = True

    if reject_immediately and "content-length" in response.headers:
        del response.headers["content-length"]

    if isinstance(response.stream, httpx.AsyncByteStream):
        response.stream = _BoundedMCPResponseStream(
            response.stream,
            method=method,
            max_bytes=max_bytes,
            max_count=max_count,
            request_id=request_payload.get("id"),
            content_type=response.headers.get("content-type", "application/json"),
            reject_immediately=reject_immediately,
        )


def validate_tool_catalog(
    tools: list[dict[str, Any]],
    *,
    max_count: int,
    max_catalog_bytes: int,
    max_definition_bytes: int,
) -> None:
    """Reject an unsafe MCP tool catalog as one indivisible response.

    Consumers must not partially stage or expose a catalog that exceeds either
    ceiling. Validation is repeated at the proxy seam so alternative clients
    and tests cannot bypass the same invariant.
    """
    if len(tools) > max_count:
        raise MCPClientError(
            "MCP tool catalog exceeds the configured maximum of "
            f"{max_count} definitions"
        )

    seen_names: set[str] = set()
    catalog_size = 0
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise MCPClientError("MCP tool catalog contains an invalid tool name")
        if name in seen_names:
            raise MCPClientError(f"MCP tool catalog contains duplicate name '{name}'")
        seen_names.add(name)

        try:
            definition_size = len(
                json.dumps(
                    tool,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise MCPClientError(
                f"MCP tool '{name}' definition is not valid JSON"
            ) from exc
        if definition_size > max_definition_bytes:
            raise MCPClientError(
                f"MCP tool '{name}' definition exceeds "
                f"the configured maximum of {max_definition_bytes} bytes"
            )
        catalog_size += definition_size
        if catalog_size > max_catalog_bytes:
            raise MCPClientError(
                "MCP tool catalog exceeds the configured maximum of "
                f"{max_catalog_bytes} serialized bytes"
            )


@asynccontextmanager
async def _open_streamable_http_client(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    tool_catalog_max_count: int,
    tool_catalog_max_bytes: int,
) -> AsyncGenerator[MCPStreams]:
    timeout = httpx.Timeout(timeout_seconds, read=MCP_SSE_READ_TIMEOUT_SECONDS)
    http_headers = {"Accept-Encoding": "identity", **headers}
    async with create_mcp_http_client(
        headers=http_headers, timeout=timeout
    ) as http_client:
        wire_max_bytes = tool_catalog_max_bytes + MCP_TOOL_LIST_PROTOCOL_OVERHEAD_BYTES
        # This coarse pre-decode bound measures server-encoded HTTP/SSE bytes;
        # validate_tool_catalog later enforces the compact semantic definition
        # budget. The fixed allowance covers JSON-RPC and SSE framing.

        async def bound_mcp_response(response: httpx.Response) -> None:
            await _bound_mcp_response(
                response,
                tools_max_bytes=wire_max_bytes,
                tools_max_count=tool_catalog_max_count,
            )

        http_client.event_hooks["response"].append(bound_mcp_response)
        async with streamable_http_client(
            url,
            http_client=http_client,
        ) as streams:
            yield streams


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

    Any HTTP status is diagnostic signal here: auth is evaluated before
    method dispatch, so a 401/403 is trustworthy even from a server that
    rejects the probe body itself.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            async with client.stream(
                "POST",
                url,
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "eneo", "version": "0.1"},
                    },
                },
            ) as response:
                if response.status_code == 401:
                    return (
                        "Authentication failed (401 Unauthorized). "
                        "Check your bearer token."
                    )
                if response.status_code == 403:
                    return "Access denied (403 Forbidden). Check your credentials."
                if response.status_code >= 500:
                    return f"Server error (HTTP {response.status_code})."
                if response.status_code >= 400:
                    return f"Server returned HTTP {response.status_code}."
                return (
                    f"Server at {url} is reachable "
                    f"(HTTP {response.status_code}) but the MCP handshake failed."
                )
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
        on_tools_list_changed: Callable[[], None] | None = None,
        identity_headers: dict[str, str] | None = None,
    ):
        """
        Initialize MCP client.

        Args:
            mcp_server: MCP server configuration
            auth_credentials: Authentication credentials from tenant settings
            timeout: Connection timeout in seconds (defaults to 30s)
            identity_headers: Acting user/tenant X-Eneo-* headers. Sent on every
                request ONLY when this server has ``forward_identity=True`` —
                identity is PII egress, opted into per server.
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
        self._on_tools_list_changed = on_tools_list_changed
        self.identity_headers = identity_headers or {}
        # Set when a tools/list_changed notification arrives on this session.
        # The proxy also re-lists the servers it just called, so this flag is a
        # protocol-correct optimization rather than the sole trigger.
        self.tools_list_changed_pending: bool = False
        # Captured from the initialize() handshake.
        self.supports_tools_list_changed: bool = False
        self.session: Optional[ClientSession] = None
        self._streams_context: AsyncContextManager[MCPStreams] | None = None
        self._session_context = None
        # Populated after a successful connect() / initialize() round-trip.
        self.server_info_name: Optional[str] = None
        self.server_info_version: Optional[str] = None

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
        """Build authentication headers for this connection."""
        headers: dict[str, str] = {}

        if self.mcp_server.http_auth_type in ("bearer", "internal"):
            # "internal" is a built-in provider on Eneo's own loopback server:
            # the token is a per-request scoped access token minted by the
            # ask path, never a stored credential.
            token = self.auth_credentials.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif self.mcp_server.http_auth_type == "api_key_header":
            # Admin-chosen header (e.g. X-Api-Key). The name is validated at
            # configuration time against HTTP token syntax and a deny-list of
            # transport/session headers, so it can be emitted as-is here.
            header_name = self.auth_credentials.get("header_name")
            token = self.auth_credentials.get("token")
            if header_name and token:
                headers[header_name] = token

        # Forward acting user/tenant identity only when this server opted in.
        # Added after the bearer token; the builder never emits Authorization,
        # so this cannot clobber it.
        if getattr(self.mcp_server, "forward_identity", False):
            headers.update(self.identity_headers)

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

        Every connection is fresh: open the transport, run ``initialize()``,
        and let the SDK terminate any server-assigned protocol session on
        teardown. Servers that hold cross-turn state key it to explicit
        handles returned in tool results, not to the transport session.
        """
        headers = await self._build_auth_headers()

        streams_context = _open_streamable_http_client(
            url=self.mcp_server.http_url,
            headers=headers,
            timeout_seconds=float(self.timeout),
            tool_catalog_max_count=self.mcp_server.tool_catalog_max_count,
            tool_catalog_max_bytes=self.mcp_server.tool_catalog_max_bytes,
        )

        streams = await streams_context.__aenter__()

        self._streams_context = streams_context
        read, write, get_session_id = streams
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
            session_id = get_session_id()
        except Exception:
            session_id = None

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
            session_id,
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
            if len(response.tools) > self.mcp_server.tool_catalog_max_count:
                raise MCPClientError(
                    "MCP tool catalog exceeds the configured maximum of "
                    f"{self.mcp_server.tool_catalog_max_count} definitions"
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

            validate_tool_catalog(
                tools,
                max_count=self.mcp_server.tool_catalog_max_count,
                max_catalog_bytes=self.mcp_server.tool_catalog_max_bytes,
                max_definition_bytes=self.mcp_server.tool_definition_max_bytes,
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
            # Result-level `_meta` (MCP spec "General fields"): servers attach
            # metadata such as OpenTelemetry GenAI usage attributes here.
            # Capped like resource meta; absent when the server sent none.
            result_meta = _truncate_meta(
                getattr(response, "meta", None) or {}, RESOURCE_META_MAX_BYTES
            )
            if result_meta:
                result["meta"] = result_meta

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
