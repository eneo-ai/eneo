"""MCP Client for connecting to and executing HTTP-based MCP servers."""

import asyncio
import json
from collections.abc import AsyncGenerator, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from types import TracebackType
from typing import (
    Annotated,
    Any,
    Callable,
    Literal,
    Optional,
    Protocol,
    TypeVar,
    cast,
)
from urllib.parse import urlsplit

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import ClientSession
from mcp.client.session import MessageHandlerFnT
from mcp.client.streamable_http import (
    GetSessionIdCallback,
    streamable_http_client,
)
from mcp.shared.message import SessionMessage
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolRequest,
    CallToolRequestParams,
    ClientRequest,
    ServerNotification,
    TextResourceContents,
    ToolListChangedNotification,
)
from pydantic import AnyUrl, BaseModel, Field, TypeAdapter, ValidationError

from eneo.files.file_reference import file_reference_base_url
from eneo.main.config import LOOPBACK_HOSTS, get_settings
from eneo.main.exceptions import (
    MCPAuthenticationError,
    MCPClientError,
    MCPToolAnswerTooLarge,
)
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.credential_transport import (
    CREDENTIAL_TRANSPORT_REQUIREMENT,
    credential_transport_violation,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
    bundled_tool_name,
    is_builtin_provider,
    is_bundled_server,
)
from eneo.mcp_servers.domain.server_address import (
    MCPServerAddress,
    loggable_server_address,
)
from eneo.mcp_servers.infrastructure.client.mcp_ui_session import (
    UiCapableClientSession,
)

logger = get_logger(__name__)

_settings = get_settings()
MCP_CONNECTION_TIMEOUT_DEFAULT = _settings.mcp_client_connect_timeout_seconds
MCP_LIST_TOOLS_TIMEOUT_DEFAULT = _settings.mcp_client_list_tools_timeout_seconds
MCP_TOOL_CALL_TIMEOUT_DEFAULT = _settings.mcp_client_call_timeout_seconds
MCP_TOOL_LIST_PROTOCOL_OVERHEAD_BYTES = 64 * 1024
MCP_INITIALIZE_RESPONSE_MAX_BYTES = 1024 * 1024
MCP_DELETE_RESPONSE_MAX_BYTES = 64 * 1024
# resources/read is only issued for MCP App view HTML. The wire ceiling counts
# JSON-escaped bytes, so allow 2x the decoded resource cap plus framing; the
# exact decoded-size check happens after parsing in read_resource().
MCP_RESOURCES_READ_RESPONSE_MAX_BYTES = (
    _settings.mcp_app_resource_max_bytes * 2 + 64 * 1024
)

# Defensive caps for resource content blocks. An adversarial MCP server can
# emit arbitrarily large `text` / `_meta` payloads. Cap the parsed resource
# blocks before they flow into persistence or citation rendering.
RESOURCE_TEXT_MAX_BYTES = 8 * 1024
RESOURCE_META_MAX_BYTES = 16 * 1024
# A tool result's `structuredContent`, which an MCP App view renders from.
STRUCTURED_CONTENT_MAX_BYTES = 256 * 1024
MCP_SSE_READ_TIMEOUT_SECONDS = 300.0

# Requests to a loopback host go direct, never through a proxy from the
# environment (HTTP_PROXY, ALL_PROXY): plain http may carry a credential only
# to these hosts because the request stays on the machine. A mount without a
# transport is how httpx itself applies NO_PROXY hosts.
_LOOPBACK_DIRECT: dict[str, httpx.AsyncBaseTransport | None] = {
    f"all://[{host}]" if ":" in host else f"all://{host}": None
    for host in LOOPBACK_HOSTS
}


class MCPInsecureCredentialTransportError(MCPClientError):
    """The server's address would expose its admin-supplied credential.

    Raised for a server saved before registration enforced https; the message
    tells the admin what to change and names neither the address nor the
    credential.
    """

    def __init__(self) -> None:
        super().__init__(CREDENTIAL_TRANSPORT_REQUIREMENT)


def _origin(url: str) -> str:
    """Scheme, host and port of ``url`` (no path, no trailing slash)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def transport_read_timeout(tool_call_timeout: float) -> float:
    """HTTP read timeout that never undercuts the tool-call budget.

    A tool call is bounded by ``tool_call_timeout``; the transport's read
    timeout must be at least as long or a slow but legitimate call (image
    generation) is cut by the transport before the tool-call timeout fires.
    """
    return max(MCP_SSE_READ_TIMEOUT_SECONDS, float(tool_call_timeout))


_Result = TypeVar("_Result")


MCPStreams = tuple[
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
    GetSessionIdCallback,
]


class MCPHttpClientFactory(Protocol):
    """Builds the HTTP client an ``MCPClient`` sends every request through,
    the diagnosis of a failed connect included. Whoever builds the client
    decides which addresses its connections may reach."""

    def __call__(
        self, *, headers: dict[str, str], timeout: httpx.Timeout
    ) -> httpx.AsyncClient: ...

    def refused_a_connection(self) -> bool:
        """Whether the factory's own rule refused a connection that one of
        its clients was to open."""
        ...


class SdkHttpClientFactory:
    """The MCP SDK's HTTP client, which refuses no connection itself."""

    def __call__(
        self, *, headers: dict[str, str], timeout: httpx.Timeout
    ) -> httpx.AsyncClient:
        # The SDK's create_mcp_http_client sets only headers and timeout and
        # takes no mounts; this client is the same plus the loopback bypass,
        # and it does not follow redirects.
        return httpx.AsyncClient(
            headers=headers, timeout=timeout, mounts=_LOOPBACK_DIRECT
        )

    def refused_a_connection(self) -> bool:
        return False


def _session_class() -> type[ClientSession]:
    """Runtime settings lookup so tests (and ops) can flip the MCP Apps flag
    without rebuilding module-level state. Flag off keeps the stock session."""
    return UiCapableClientSession if get_settings().mcp_apps_enabled else ClientSession


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


# Requests whose refusal the client reports as a failure of that request.
_REFUSABLE_METHODS = frozenset({"tools/call", "resources/read"})


@dataclass
class _RequestRefusal:
    """The HTTP status the server refused a waiting request with, by method.

    A refusal (an error status or a redirect) fails the SDK's transport, which
    then cancels the request that waits for the answer. The status tells that
    cancellation apart from a cancelled caller.
    """

    statuses: dict[str, int] = field(default_factory=dict[str, int])
    # The status of the refusal that failed the transport. The connection
    # takes no further request then: its scope stays cancelled, so another
    # request would be cancelled with no status of its own.
    failed_with: int | None = None

    def refuse_on_failed_connection(self, operation: str) -> None:
        if self.failed_with is not None:
            raise MCPClientError(
                f"{operation} failed: the connection failed after the server "
                f"answered HTTP {self.failed_with}"
            )


@dataclass
class _ToolAnswerCeiling:
    """The largest tool answer one client accepts, shared by its streams.

    A server may send the answer to ``tools/call`` on the response to that
    request, on the stream the client keeps open to listen, or on a stream
    the client opens again after the server closed one. So every response
    stream of the client that has no ceiling of its own (the handshake, the
    catalog and the end of a session have one) counts against this one: each
    stream all its bytes, from the first to the last, whatever they carry
    (the client cannot tell an answer from anything else a server sends
    before it has decoded it). A stream that passes ``max_bytes`` is closed
    and the tool call that waits fails as too large. A compressed stream is
    closed unread and that call fails as any other failed call, unless the
    stream also declares a size over ``max_bytes``: that one is too large.
    """

    max_bytes: int
    # The JSON-RPC id of the tools/call request that is out, so that a stream
    # other than its own response can fail it. None while no call waits.
    waiting_request_id: str | int | None = None
    # Set by the stream that failed the waiting call for its size.
    answer_too_large: bool = False


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
        tool_answer_ceiling: _ToolAnswerCeiling | None = None,
        compressed_tool_answer: bool = False,
    ) -> None:
        self._stream = stream
        self._method = method
        self._max_bytes = max_bytes
        self._max_count = max_count
        self._request_id = request_id
        self._is_sse = content_type.lower().startswith("text/event-stream")
        self._reject_immediately = reject_immediately
        self._tool_answer_ceiling = tool_answer_ceiling
        self._compressed_tool_answer = compressed_tool_answer

    def _stopped(self, *, compressed: bool = False) -> bytes | None:
        """What the SDK reads in place of the response that was stopped.

        A stream that counts against a tool answer ceiling fails the tool
        call that waits. When none does there is nobody to tell (None): the
        stream just ends.
        """
        ceiling = self._tool_answer_ceiling
        if ceiling is None:
            return self._error_response()
        if ceiling.waiting_request_id is None:
            return None
        if compressed:
            return self._error_response(
                f"MCP {self._method} response is compressed although an "
                "identity encoding was asked for"
            )
        # The SDK only sees a JSON-RPC error, which the server could send as
        # well; the flag is how the client knows it was the ceiling.
        ceiling.answer_too_large = True
        return self._error_response()

    def _error_response(self, message: str | None = None) -> bytes:
        if message is None:
            message = (
                f"MCP {self._method} wire response exceeds the configured "
                f"maximum of {self._max_bytes} bytes"
            )
        ceiling = self._tool_answer_ceiling
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id
                if ceiling is None
                else ceiling.waiting_request_id,
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
        if self._reject_immediately or self._compressed_tool_answer:
            await self._stream.aclose()
            stopped = self._stopped(compressed=self._compressed_tool_answer)
            if stopped is not None:
                yield stopped
            return

        async for chunk in self._stream:
            received_bytes += len(chunk)
            if received_bytes > self._max_bytes:
                await self._stream.aclose()
                stopped = self._stopped()
                if stopped is not None:
                    yield stopped
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
    response: httpx.Response,
    *,
    tools_max_bytes: int,
    tools_max_count: int,
    tool_answer_ceiling: _ToolAnswerCeiling | None = None,
) -> None:
    """Install method-specific pre-decode ceilings on untrusted MCP responses.

    With ``tool_answer_ceiling``, every response without a ceiling of its own
    counts against that one.
    """
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

    # A request without a JSON-RPC body is the client listening (GET).
    request_payload = _json_rpc_request_payload(response.request) or {}
    method = request_payload.get("method")
    ceiling: _ToolAnswerCeiling | None = None
    if method == "tools/list":
        bounded_method = "tools/list"
        max_bytes = tools_max_bytes
        max_count: int | None = tools_max_count
    elif method == "initialize":
        bounded_method = "initialize"
        max_bytes = MCP_INITIALIZE_RESPONSE_MAX_BYTES
        max_count = None
    elif method == "resources/read":
        bounded_method = "resources/read"
        max_bytes = MCP_RESOURCES_READ_RESPONSE_MAX_BYTES
        max_count = None
    elif tool_answer_ceiling is not None:
        ceiling = tool_answer_ceiling
        bounded_method = "tools/call"
        max_bytes = ceiling.max_bytes
        max_count = None
    else:
        return

    compressed = response.headers.get("content-encoding", "identity").lower() not in {
        "",
        "identity",
    }
    if compressed:
        # The stream ceiling counts bytes before HTTPX decoding. Requiring an
        # identity body prevents a small compressed response from expanding
        # beyond the configured bound during SDK JSON parsing.
        del response.headers["content-encoding"]

    declared_too_large = False
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_bytes = int(content_length)
        except ValueError:
            declared_bytes = None
        if declared_bytes is not None and declared_bytes > max_bytes:
            declared_too_large = True

    # A tool answer has an outcome of its own for "too large", so one that is
    # only compressed is refused as that. The handshake and the catalog have
    # one refusal for both.
    compressed_tool_answer = (
        compressed and ceiling is not None and not declared_too_large
    )
    reject_immediately = declared_too_large or (compressed and ceiling is None)
    if (
        reject_immediately or compressed_tool_answer
    ) and "content-length" in response.headers:
        del response.headers["content-length"]

    if isinstance(response.stream, httpx.AsyncByteStream):
        response.stream = _BoundedMCPResponseStream(
            response.stream,
            method=bounded_method,
            max_bytes=max_bytes,
            max_count=max_count,
            request_id=request_payload.get("id"),
            content_type=response.headers.get("content-type", "application/json"),
            reject_immediately=reject_immediately,
            tool_answer_ceiling=ceiling,
            compressed_tool_answer=compressed_tool_answer,
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
    read_timeout_seconds: float = MCP_SSE_READ_TIMEOUT_SECONDS,
    tool_catalog_max_count: int,
    tool_catalog_max_bytes: int,
    tool_answer_ceiling: _ToolAnswerCeiling | None = None,
    request_refusal: _RequestRefusal | None = None,
    terminate_on_close: bool = True,
    http_client_factory: MCPHttpClientFactory,
) -> AsyncGenerator[MCPStreams]:
    timeout = httpx.Timeout(timeout_seconds, read=read_timeout_seconds)
    http_headers = {"Accept-Encoding": "identity", **headers}
    async with http_client_factory(
        headers=http_headers, timeout=timeout
    ) as http_client:
        # The SDK's client follows redirects. No MCP client of Eneo does: a
        # redirect would take the request, and credential headers with it,
        # to an address that nobody registered.
        http_client.follow_redirects = False
        wire_max_bytes = tool_catalog_max_bytes + MCP_TOOL_LIST_PROTOCOL_OVERHEAD_BYTES
        # This coarse pre-decode bound measures server-encoded HTTP/SSE bytes;
        # validate_tool_catalog later enforces the compact semantic definition
        # budget. The fixed allowance covers JSON-RPC and SSE framing.

        async def bound_mcp_response(response: httpx.Response) -> None:
            await _bound_mcp_response(
                response,
                tools_max_bytes=wire_max_bytes,
                tools_max_count=tool_catalog_max_count,
                tool_answer_ceiling=tool_answer_ceiling,
            )

        http_client.event_hooks["response"].append(bound_mcp_response)
        if tool_answer_ceiling is not None:
            ceiling = tool_answer_ceiling

            async def note_waiting_tool_call(request: httpx.Request) -> None:
                # Noted when the request leaves, not when it is answered: the
                # server may send the answer on another stream first.
                payload = _json_rpc_request_payload(request) or {}
                request_id = payload.get("id")
                if payload.get("method") == "tools/call" and isinstance(
                    request_id, (str, int)
                ):
                    ceiling.waiting_request_id = request_id

            http_client.event_hooks["request"].append(note_waiting_tool_call)
        if request_refusal is not None:
            refusal = request_refusal

            async def note_refused_request(response: httpx.Response) -> None:
                if not (response.is_error or response.has_redirect_location):
                    return
                payload = _json_rpc_request_payload(response.request) or {}
                method = payload.get("method")
                if isinstance(method, str) and method in _REFUSABLE_METHODS:
                    refusal.statuses[method] = response.status_code

            http_client.event_hooks["response"].append(note_refused_request)
        async with streamable_http_client(
            url,
            http_client=http_client,
            terminate_on_close=terminate_on_close,
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

    if isinstance(exc, httpx.HTTPStatusError):
        return _diagnose_response(exc.response)

    # Skip noise exceptions
    if isinstance(exc, (GeneratorExit, KeyboardInterrupt, SystemExit)):
        return ""
    if "cancel scope" in str(exc).lower():
        return ""

    return str(exc)


# The longest redirect target an error message quotes; a longer one is left out.
MCP_REDIRECT_TARGET_MAX_LENGTH = 200
_REGISTERED_ADDRESS = TypeAdapter[MCPServerAddress](MCPServerAddress)


def _address(url: httpx.URL) -> str:
    """A URL without user info, query and fragment, still percent-encoded."""
    path = url.raw_path.split(b"?", 1)[0].decode("ascii")
    return f"{url.scheme}://{url.netloc.decode('ascii')}{path}"


def _redirect_target(response: httpx.Response) -> str | None:
    """Where a redirect points, when that is an address an administrator
    can register instead as it is written; None otherwise.

    The server chose this text and an administrator reads it, so it is shown
    percent-encoded (no line break or control character can come through),
    without user info, query and fragment, and of a bounded length. The type
    that reads a registered address decides the rest: a text it refuses
    (another scheme, no host) or reads as another address (a host taken from
    the path, a number read as an IP address) names no target. Nor does the
    address that was asked.
    """
    try:
        target = response.url.join(response.headers["location"])
    except httpx.InvalidURL:
        return None
    address = _address(target)
    if len(address) > MCP_REDIRECT_TARGET_MAX_LENGTH:
        return None
    try:
        registered = _REGISTERED_ADDRESS.validate_python(address)
    except ValidationError:
        return None
    if str(registered) != address:
        return None
    return None if address == _address(response.url) else address


def _diagnose_response(response: httpx.Response) -> str:
    """Describe the HTTP result without disclosing request or redirect secrets."""
    server = loggable_server_address(str(response.request.url))
    if response.status_code == 401:
        return "Authentication failed (401 Unauthorized). Check your bearer token."
    if response.has_redirect_location:
        target = _redirect_target(response)
        return (
            f"Server at {server} answered with a redirect "
            f"(HTTP {response.status_code})"
            f"{f' to {target}' if target else ''}. Eneo does not "
            "follow redirects: register the address the server "
            "redirects to."
        )
    if response.status_code == 403:
        return "Access denied (403 Forbidden). Check your credentials."
    if response.status_code >= 500:
        return f"Server error (HTTP {response.status_code})."
    if response.status_code >= 400:
        return f"Server returned HTTP {response.status_code}."
    return (
        f"Server at {server} is reachable "
        f"(HTTP {response.status_code}) but the MCP handshake failed."
    )


async def _diagnose_http(
    url: str,
    headers: dict[str, str],
    *,
    http_client_factory: MCPHttpClientFactory,
) -> str:
    """Quick HTTP request to diagnose the real error when MCP protocol fails.

    The MCP library's anyio TaskGroups can swallow the actual HTTP error
    (e.g. 401) and replace it with a cancel scope error. This makes a
    direct HTTP request to surface the real issue.

    Any HTTP status is diagnostic signal here: auth is evaluated before
    method dispatch, so a 401/403 is trustworthy even from a server that
    rejects the probe body itself.

    A message names the server by ``loggable_server_address``: it is logged,
    and the path or query of the address can carry a token.
    """
    server = loggable_server_address(url)
    try:
        async with http_client_factory(
            headers=headers, timeout=httpx.Timeout(5.0)
        ) as client:
            async with client.stream(
                "POST",
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                # The redirect is what this request may have to report.
                follow_redirects=False,
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
                return _diagnose_response(response)
    except httpx.ConnectError:
        return f"Could not connect to {server}. Verify the URL and that the server is running."
    except httpx.TimeoutException:
        return f"Connection to {server} timed out."
    except Exception:
        pass
    return "Connection failed for unknown reasons."


def loopback_endpoint(name: str) -> str:
    """URL of one of Eneo's own loopback MCP servers, mounted under ``name``."""
    base = get_settings().internal_mcp_base_url.rstrip("/")
    return f"{base}/internal-mcp/{name}/mcp"


def bundled_endpoint(tool: str) -> str | None:
    """URL of ``tool`` in the bundled tool runtime, if one is configured."""
    settings = get_settings()
    if not settings.tool_runtime_url or not settings.tool_runtime_token:
        return None
    return f"{settings.tool_runtime_url.rstrip('/')}/mcp/{tool}"


def _bundled_endpoint_of(mcp_server: MCPServer) -> str | None:
    tool = bundled_tool_name(mcp_server.http_url)
    return bundled_endpoint(tool) if tool else None


def endpoint_url(mcp_server: MCPServer) -> str:
    """URL to connect to for ``mcp_server``.

    A built-in provider runs on Eneo's own loopback server of its purpose, so
    its endpoint follows ``INTERNAL_MCP_BASE_URL`` as it is configured now.
    The URL stored on its row is the value from the last time the row was
    saved: it goes stale when the setting changes, and the scoped token minted
    for a built-in provider must only ever reach Eneo itself.

    A bundled server likewise follows ``TOOL_RUNTIME_URL`` as it is configured
    now; its stored URL only names the runtime tool it serves. While the
    runtime is not configured the stored URL is returned for display, and
    connecting is refused (see ``_build_auth_headers``).
    """
    if is_builtin_provider(mcp_server.http_auth_type):
        return loopback_endpoint(mcp_server.purpose)
    if is_bundled_server(mcp_server.http_auth_type):
        return _bundled_endpoint_of(mcp_server) or mcp_server.http_url
    return mcp_server.http_url


# A disconnect waits this long for the host to unwind the SDK contexts (the
# session's receive loop, the transport's session termination) before it is
# cancelled.
MCP_DISCONNECT_TIMEOUT_SECONDS = 10.0

# Strong references to running connection hosts: asyncio keeps only weak
# ones, and a host whose client has been dropped must still finish its
# teardown. Drained at shutdown.
_connection_hosts: dict[asyncio.Task[None], "_ConnectionHost"] = {}


def _retrieve_exception(future: asyncio.Future[None]) -> None:
    if not future.cancelled():
        future.exception()


class _ConnectionHost:
    """The task that owns one server connection.

    anyio binds the cancel scopes of ``streamable_http_client`` and
    ``ClientSession`` to the task that enters them: only that task may exit
    them, in reverse order, with no other scope pushed on top meanwhile.
    Entering them on whichever task happened to connect (a request task, a
    gather child, a generator finalizer run by the garbage collector) is what
    leaked their HTTP read/write loops before (#361, #1225). The host enters
    both contexts in one coroutine on a task of its own, so they always nest
    correctly, and leaves them when asked. Requests still go straight to the
    ``ClientSession`` from the calling task: the SDK multiplexes them by
    request id.
    """

    def __init__(
        self,
        client: "MCPClient",
        headers: dict[str, str],
        message_handler: MessageHandlerFnT,
    ) -> None:
        self._client = client
        self._headers = headers
        self._message_handler = message_handler
        self._ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._stop = asyncio.Event()
        self._cancel_timer: asyncio.TimerHandle | None = None
        self.task = asyncio.create_task(
            self._run(), name=f"mcp-connection:{client.mcp_server.name}"
        )
        _connection_hosts[self.task] = self
        self.task.add_done_callback(self._settle)

    def _settle(self, task: asyncio.Task[None]) -> None:
        _connection_hosts.pop(task, None)
        if self._cancel_timer is not None:
            self._cancel_timer.cancel()
        if not self._ready.done():
            # The host ended before its handshake: cancelled before it ran
            # at all (a shutdown drain), or on a path that reported nothing.
            self._ready.set_exception(
                MCPClientError(
                    "The MCP connection was closed before its handshake finished"
                )
            )

    async def wait_ready(self) -> None:
        """Return once the session is initialized; raise what connecting raised.

        Shielded: a cancelled connector must not cancel the handshake's
        future, which the host still completes and reports into.
        """
        await asyncio.shield(self._ready)

    def request_stop(self) -> None:
        """Ask the host to leave its contexts; it does so without being awaited.

        Arms the disconnect deadline too: a host that has not left them by
        then is cancelled, whether or not anyone is still waiting for it.
        """
        self._stop.set()
        if self._cancel_timer is None:
            self._cancel_timer = asyncio.get_running_loop().call_later(
                MCP_DISCONNECT_TIMEOUT_SECONDS, self.task.cancel
            )
        # Nobody may await the handshake any more; a failure it still reports
        # must not surface as an unretrieved future exception.
        self._ready.add_done_callback(_retrieve_exception)

    async def stop(self, timeout: float) -> None:
        """Leave the contexts and wait for the host, bounded by ``timeout``.

        Past the deadline, or once the caller stops waiting (its finalization
        budget ran out, it was cancelled), the host is cancelled instead:
        cancellation unwinds the same contexts, only without the transport's
        graceful session termination.
        """
        self.request_stop()
        try:
            async with asyncio.timeout(timeout):
                await asyncio.wait({self.task})
        except TimeoutError:
            logger.warning(
                "MCP connection to %s did not close within %.0fs; cancelling it",
                self._client.mcp_server.name,
                timeout,
            )
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        except asyncio.CancelledError:
            # Not awaited: the scope cancelling this task would cancel that
            # wait too. The host finishes unwinding on its own.
            self.task.cancel()
            raise

    async def _run(self) -> None:
        client = self._client
        session: ClientSession | None = None
        try:
            async with client.open_transport(self._headers) as (
                read,
                write,
                get_session_id,
            ):
                logger.debug(
                    "Streamable HTTP transport connected to %s",
                    loggable_server_address(client.endpoint_url),
                )
                async with _session_class()(
                    read, write, message_handler=self._message_handler
                ) as session:
                    init_result = await session.initialize()
                    if self._stop.is_set():
                        # Asked to stop during the handshake: the connector gave
                        # up (a later connect may already have published its
                        # own session) or a shutdown drain is running, and a
                        # connector still waiting must not get a dead host.
                        self._ready.set_exception(
                            MCPClientError(
                                "The MCP connection was closed before its "
                                "handshake finished"
                            )
                        )
                        return
                    client.record_handshake(init_result, get_session_id)
                    client.session = session
                    self._ready.set_result(None)
                    await self._stop.wait()
        except BaseException as exc:
            interrupted = isinstance(
                exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
            )
            if not self._ready.done():
                # Connecting failed; the connector reports it. The contexts
                # entered so far have already been left on this task.
                if interrupted:
                    # Only the host itself was cancelled (a shutdown drain, a
                    # stop deadline), never the connector, which must not see
                    # a cancellation it did not receive.
                    self._ready.set_exception(
                        MCPClientError(
                            "The MCP connection was closed before its handshake "
                            "finished"
                        )
                    )
                    raise
                self._ready.set_exception(exc)
                return
            client.log_teardown_error(exc)
            if interrupted:
                raise
        finally:
            if not self._ready.done():
                self._ready.set_result(None)
            if client.session is session:
                client.session = None
            client.detach_host(self)


async def drain_connection_hosts(timeout: float) -> int:
    """Close the connections still open at shutdown; return how many there were.

    Every turn closes its own connections, so this finds none unless a
    request was cut off before its cleanup ran. Each host is asked to leave
    its contexts, as ``disconnect()`` would, so a healthy connection ends the
    way a disconnect ends it, session terminated, rather than by cancellation
    unwinding the SDK's scopes; a host that has not left them within
    ``timeout`` is cancelled and joined. Runs while the loopback internal-MCP
    servers are still up and before the pools the connections use close.
    """
    hosts = {task: host for task, host in _connection_hosts.items() if not task.done()}
    if not hosts:
        return 0
    logger.warning(
        "%d MCP connection(s) still open at shutdown; closing them", len(hosts)
    )
    for host in hosts.values():
        host.request_stop()
    await asyncio.wait(set(hosts), timeout=timeout)
    unfinished = {task for task in hosts if not task.done()}
    if unfinished:
        logger.error(
            "%d of %d MCP connection(s) did not close within %.0fs at shutdown; "
            "cancelling them",
            len(unfinished),
            len(hosts),
            timeout,
        )
        for task in unfinished:
            task.cancel()
        await asyncio.wait(unfinished, timeout=timeout)
    return len(hosts)


@dataclass(frozen=True)
class MCPToolAnswer:
    """A tool's answer as the server sent it, for a caller that reads it as data.

    ``text_blocks`` holds each text block as sent, in order. ``other_blocks``
    counts the content blocks that are not text (images, audio, resources,
    resource links, and any kind this client does not know): their content is
    not part of this answer, and the count is how the caller knows that there
    was more. ``structured`` is the structured content as sent: nothing has
    checked it against the tool's output schema, the caller validates the
    answer against its own contract. ``is_error`` is the tool's own statement
    that it failed, not a failed call. The result's ``_meta`` is not part of
    an answer.
    """

    text_blocks: tuple[str, ...]
    other_blocks: int
    structured: dict[str, object] | None
    is_error: bool


class _TextBlock(BaseModel):
    type: Literal["text"]
    text: str


class _OtherBlock(BaseModel):
    type: str


class _ToolCallResult(BaseModel):
    """The result of ``tools/call``, read as far as an answer goes.

    The SDK's own model refuses a whole result for one content block of a
    kind it does not know. Here such a block is one more that is not text.
    """

    content: list[
        Annotated[_TextBlock | _OtherBlock, Field(union_mode="left_to_right")]
    ]
    structured: dict[str, object] | None = Field(
        default=None, alias="structuredContent"
    )
    is_error: bool = Field(default=False, alias="isError")


class MCPClient:
    """Client for interacting with HTTP-based MCP servers.

    The connection lives on its own task (``_ConnectionHost``); ``connect``
    and ``disconnect`` may be called from any task.
    """

    def __init__(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None,
        timeout: int | None = None,
        list_tools_timeout: int | None = None,
        tool_call_timeout: int | None = None,
        on_tools_list_changed: Callable[[], None] | None = None,
        identity_headers: dict[str, str] | None = None,
        tool_call_max_bytes: int | None = None,
        terminate_session_on_close: bool = True,
        http_client_factory: MCPHttpClientFactory | None = None,
    ):
        """
        Initialize MCP client.

        Args:
            mcp_server: MCP server configuration
            auth_credentials: Authentication credentials from tenant settings
            timeout: Connection timeout in seconds (defaults to 30s)
            identity_headers: Acting user/tenant X-Eneo-* headers. Sent on every
                request for bundled servers (opaque IDs only). External servers
                require ``forward_identity=True`` for identity egress.
            tool_call_max_bytes: The largest tool answer this client accepts,
                counted as it arrives and before it is decoded, on every
                stream the server can send it on (see ``_ToolAnswerCeiling``).
                None accepts any size; give it on a client that makes one
                call at a time, because a stopped answer is reported for the
                call in flight.
            terminate_session_on_close: Whether closing asks the server to end
                the session it assigned. That is one more request, whose
                answer the close waits for up to the transport's read
                timeout. False for a caller that has to be done within its
                time; the server's session then expires on its own.
            http_client_factory: Builds the HTTP client every request of
                this client goes through. The SDK's by default; a caller
                that may reach only addresses it vetted gives one whose
                connections are vetted.
            on_tools_list_changed: Fired (best-effort) when the server pushes a
                ``notifications/tools/list_changed``. Progressive-discovery
                servers emit this after a tool like ``load_tools`` activates new
                tools; the proxy reacts by re-listing so the freshly activated
                tools become callable on the next model turn.
        """
        super().__init__()
        self.mcp_server = mcp_server
        self.endpoint_url = endpoint_url(mcp_server)
        self.auth_credentials = auth_credentials or {}
        self.timeout = timeout or MCP_CONNECTION_TIMEOUT_DEFAULT
        self.list_tools_timeout = list_tools_timeout or MCP_LIST_TOOLS_TIMEOUT_DEFAULT
        self.tool_call_timeout = tool_call_timeout or MCP_TOOL_CALL_TIMEOUT_DEFAULT
        self._on_tools_list_changed = on_tools_list_changed
        self.identity_headers = identity_headers or {}
        self._tool_answer_ceiling = (
            _ToolAnswerCeiling(tool_call_max_bytes)
            if tool_call_max_bytes is not None
            else None
        )
        self._request_refusal = _RequestRefusal()
        self._terminate_session_on_close = terminate_session_on_close
        self._http_client_factory = http_client_factory or SdkHttpClientFactory()
        # Set when a tools/list_changed notification arrives on this session.
        # The proxy also re-lists the servers it just called, so this flag is a
        # protocol-correct optimization rather than the sole trigger.
        self.tools_list_changed_pending: bool = False
        # Captured from the initialize() handshake.
        self.supports_tools_list_changed: bool = False
        self.session: Optional[ClientSession] = None
        # The task that owns the SDK's transport and session contexts (see
        # _ConnectionHost). Requests use ``session`` from any task.
        self._host: _ConnectionHost | None = None
        # Serialises connect(): two connects racing would each start a host.
        self._connect_lock = asyncio.Lock()
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
        """Build authentication headers for this connection.

        Every request the client sends carries the headers built here (the
        transport and the diagnostic probe alike), so this is where a
        credential bound for a plain-http address is refused. Eneo's own
        loopback servers (knowledge, files) are exempt: their token is minted
        per request for Eneo itself and goes to the deployment's
        ``INTERNAL_MCP_BASE_URL``, not to an address an admin entered.
        """
        if (
            not self.mcp_server.is_internal
            and credential_transport_violation(
                self.mcp_server.http_auth_type, self.endpoint_url
            )
            is not None
        ):
            raise MCPInsecureCredentialTransportError()
        headers: dict[str, str] = {}

        if self.mcp_server.http_auth_type in ("bearer", "internal"):
            # "internal" is a built-in provider on Eneo's own loopback server:
            # the token is a per-request scoped access token minted by the
            # ask path, never a stored credential.
            token = self.auth_credentials.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif is_bundled_server(self.mcp_server.http_auth_type):
            # The bundled tool runtime shares one deployment secret with the
            # backend; it is read from settings on every connect so rotating
            # it needs only a redeploy of both sides. The secret is sent only
            # to the runtime as the deployment configures it now, never to
            # whatever URL the row still carries.
            if self.endpoint_url != _bundled_endpoint_of(self.mcp_server):
                raise MCPClientError(
                    "The bundled tool runtime is not configured for this deployment"
                )
            settings = get_settings()
            headers["Authorization"] = f"Bearer {settings.tool_runtime_token}"
            # Where Eneo's signed file links point. The runtime fetches files
            # only from this origin, so a model-supplied URL can never steer it
            # elsewhere, and the deployment configures the origin once.
            base_url = file_reference_base_url(settings)
            if base_url:
                headers["X-Eneo-File-Origin"] = _origin(base_url)
            # Whether the reader is shown tool views (MCP Apps), so a tool can
            # tell the model what the reader already sees beside the answer.
            if settings.mcp_apps_enabled and settings.mcp_app_content_base_url:
                headers["X-Eneo-Tool-Views"] = "shown"
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
        if is_bundled_server(self.mcp_server.http_auth_type):
            # Bundled execution needs opaque IDs for cache isolation and scheduling,
            # including registrations made before identity forwarding was enabled.
            headers.update(
                {
                    key: value
                    for key, value in self.identity_headers.items()
                    if key.lower() in ("x-eneo-user-id", "x-eneo-tenant-id")
                }
            )
        elif getattr(self.mcp_server, "forward_identity", False):
            headers.update(self.identity_headers)

        return headers

    def open_transport(
        self, headers: dict[str, str]
    ) -> AbstractAsyncContextManager[MCPStreams]:
        """Configure the transport; its connection host owns entering and closing it."""
        return _open_streamable_http_client(
            url=self.endpoint_url,
            headers=headers,
            timeout_seconds=float(self.timeout),
            read_timeout_seconds=transport_read_timeout(self.tool_call_timeout),
            tool_catalog_max_count=self.mcp_server.tool_catalog_max_count,
            tool_catalog_max_bytes=self.mcp_server.tool_catalog_max_bytes,
            tool_answer_ceiling=self._tool_answer_ceiling,
            request_refusal=self._request_refusal,
            terminate_on_close=self._terminate_session_on_close,
            http_client_factory=self._http_client_factory,
        )

    async def connect(self) -> None:
        """Connect to the HTTP-based MCP server.

        Timeout is delegated to the HTTP transport (not asyncio.wait_for)
        to avoid conflicts with anyio's cancel scopes in the MCP library.
        """
        try:
            await self._connect_internal()
        except MCPClientError:
            raise
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except BaseException as e:
            error_msg = _extract_error_message(e)
            if not error_msg and self._http_client_factory.refused_a_connection():
                # Asking the server why would resolve its name again, and an
                # answer the rule allows then would not explain this failure.
                error_msg = (
                    "The address the server's name answered is not one this "
                    "client may connect to."
                )
            elif not error_msg:
                # Cancel scope or other unhelpful error — do a direct HTTP
                # request to surface the real issue (e.g. 401).
                try:
                    diagnostic_headers = await self._build_auth_headers()
                except Exception:
                    # Still produce a diagnostic if auth header construction
                    # fails for any unexpected reason.
                    diagnostic_headers = {}
                error_msg = await _diagnose_http(
                    self.endpoint_url,
                    diagnostic_headers,
                    http_client_factory=self._http_client_factory,
                )
            logger.error(
                f"Failed to connect to MCP server {self.mcp_server.name}: {error_msg}"
            )
            raise MCPClientError(error_msg) from e

    async def _connect_internal(self) -> None:
        """Start the connection host and wait for its handshake.

        Errors are NOT wrapped here — they propagate to connect() which
        has the diagnostic fallback for unhelpful cancel scope errors.

        Every connection is fresh: open the transport, run ``initialize()``,
        and let the SDK terminate any server-assigned protocol session on
        teardown unless the caller explicitly keeps the transport session.
        Servers that hold cross-turn state key it to explicit
        handles returned in tool results, not to the transport session.

        Idempotent: while a host is attached and running, connecting again
        keeps it rather than opening a second connection beside it. A host
        that ended on its own (the server closed the stream, a read timed
        out) has detached itself; connecting again then opens a new one.
        ``disconnect()`` detaches it too.
        """
        async with self._connect_lock:
            if self._host is not None and not self._host.task.done():
                return
            headers = await self._build_auth_headers()
            host = _ConnectionHost(self, headers, self._handle_session_message)
            try:
                await host.wait_ready()
            except BaseException:
                # A failed handshake has already left its contexts; a cancelled
                # connector leaves the host to finish on its own and unwind.
                host.request_stop()
                raise
            self._host = host

    def detach_host(self, host: "_ConnectionHost") -> None:
        """Forget ``host`` once it has ended, so ``connect()`` reports reality.

        Called by the host itself as it leaves its contexts, on whichever
        path ended it; a host already replaced or detached is left alone.
        """
        if self._host is host:
            self._host = None

    def record_handshake(
        self, init_result: Any, get_session_id: Callable[[], str | None]
    ) -> None:
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

    def log_teardown_error(self, exc: BaseException) -> None:
        if isinstance(exc, asyncio.CancelledError):
            return
        message = str(exc).lower()
        if "cancel scope" in message or "different task" in message:
            # The host is the only task that enters or leaves these contexts;
            # this would mean a regression of that ownership, not a flaky server.
            logger.error(
                "MCP connection to %s hit a task-boundary error on teardown: %s",
                self.mcp_server.name,
                exc,
            )
        else:
            logger.warning(
                "MCP connection to %s ended with an error: %s",
                self.mcp_server.name,
                _extract_error_message(exc) or exc,
            )

    async def _send_request(self, request: Coroutine[Any, Any, _Result]) -> _Result:
        """End a pending RPC when its separately owned connection ends."""
        host = self._host
        if host is None:
            return await request
        pending = asyncio.create_task(request)
        try:
            await asyncio.wait(
                {pending, host.task}, return_when=asyncio.FIRST_COMPLETED
            )
            if pending.done():
                return pending.result()
            raise MCPClientError("MCP connection closed before the request completed")
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    async def list_tools(self) -> list[dict[str, Any]]:
        """
        List all available tools from the MCP server.

        Returns:
            List of tool definitions
        """
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        try:
            async with asyncio.timeout(self.list_tools_timeout):
                response = await self._send_request(self.session.list_tools())
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
                raw_meta = getattr(tool, "meta", None) or getattr(tool, "_meta", None)
                tools.append(
                    {
                        "name": tool.name,
                        "title": title,
                        "description": tool.description,
                        "input_schema": tool.inputSchema,
                        # Serialized into the catalog dicts below, so metadata
                        # counts against the same per-definition and catalog
                        # byte ceilings as the rest of the contract.
                        "meta": (
                            raw_meta
                            if isinstance(raw_meta, dict) and raw_meta
                            else None
                        ),
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

        except asyncio.CancelledError:
            # The caller was cancelled (e.g. the chat stream ended); that is
            # not a server failure. The catch-all below would report it as one.
            raise
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

    async def call_tool_as_sent(
        self, tool_name: str, arguments: dict[str, object]
    ) -> MCPToolAnswer:
        """Call a tool and return its answer as the server sent it.

        For a caller that reads the answer as data. ``call_tool`` is chat's:
        it hands on the content blocks for a model and does not read the
        structured content. Exactly one request is sent, ``tools/call``.

        The wait for the answer has no time limit of its own: the caller
        bounds the whole exchange, the connect and the close included (see
        ``UnattendedToolCaller``), and a second clock here would only ever
        end after that one.
        """
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        ceiling = self._tool_answer_ceiling
        try:
            # Not the session's call_tool: that follows the call with a
            # request for the tool list, which can hang or fail on its own,
            # and fails the call on the tool's output schema. The caller
            # checks the answer against its own contract.
            response = await self._send_request(
                self.session.send_request(
                    ClientRequest(
                        CallToolRequest(
                            params=CallToolRequestParams(
                                name=tool_name, arguments=dict(arguments)
                            )
                        )
                    ),
                    _ToolCallResult,
                )
            )
        except Exception as e:
            if ceiling is not None and ceiling.answer_too_large:
                raise MCPToolAnswerTooLarge(
                    "Tool call failed: the server sent more than "
                    f"{ceiling.max_bytes} bytes in one response"
                ) from e
            raise MCPClientError(
                f"Tool call failed: {_extract_error_message(e) or str(e)}"
            ) from e
        finally:
            if ceiling is not None:
                # No call waits any more: a stream stopped from here on has
                # nobody to tell, and the next call starts with nothing found.
                ceiling.waiting_request_id = None
                ceiling.answer_too_large = False

        text_blocks = tuple(
            block.text for block in response.content if isinstance(block, _TextBlock)
        )
        return MCPToolAnswer(
            text_blocks=text_blocks,
            other_blocks=len(response.content) - len(text_blocks),
            structured=response.structured,
            is_error=response.is_error,
        )

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
        self._request_refusal.refuse_on_failed_connection("Tool call")
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        self._request_refusal.statuses.pop("tools/call", None)
        try:
            async with asyncio.timeout(self.tool_call_timeout):
                response = await self._send_request(
                    self.session.call_tool(tool_name, arguments=arguments)
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
                            # Base64 bytes of a binary resource. The proxy
                            # admits it as a generated file (document and
                            # spreadsheet providers) or strips it; it never
                            # reaches the model.
                            "blob": getattr(resource, "blob", None),
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

            # Kept whole or not at all: a view handed part of its data would
            # show something the tool never returned.
            structured: object = getattr(response, "structuredContent", None)
            if isinstance(structured, dict) and structured:
                structured_bytes = len(
                    json.dumps(structured, ensure_ascii=False, default=str).encode()
                )
                if structured_bytes <= STRUCTURED_CONTENT_MAX_BYTES:
                    result["structured_content"] = structured
                else:
                    logger.warning(
                        "Dropped %d bytes of structured content from %s on %s (max %d)",
                        structured_bytes,
                        tool_name,
                        self.mcp_server.name,
                        STRUCTURED_CONTENT_MAX_BYTES,
                    )

            logger.info(f"Called tool {tool_name} on {self.mcp_server.name}")
            return result

        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as e:
            raise MCPClientError(
                f"Tool call failed: request timed out after {self.tool_call_timeout}s"
            ) from e
        except MCPClientError:
            refused = self._request_refusal.statuses.get("tools/call")
            if refused is None:
                raise
            self._request_refusal.failed_with = refused
            message = f"Tool call failed: the server answered HTTP {refused}"
            if refused in (401, 403):
                raise MCPAuthenticationError(message) from None
            raise MCPClientError(message) from None
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

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read one resource from the MCP server (used for MCP App view HTML).

        Returns ``{"uri", "text", "mime_type", "meta"}`` for the first content
        block. The decoded text is bounded by ``mcp_app_resource_max_bytes``
        (the wire response is separately pre-bounded before SDK decoding); the
        general 8 KiB embedded-resource cap deliberately does not apply here.
        """
        self._request_refusal.refuse_on_failed_connection("Resource read")
        if not self.session:
            raise MCPClientError("Not connected to MCP server")

        self._request_refusal.statuses.pop("resources/read", None)
        try:
            async with asyncio.timeout(self.tool_call_timeout):
                result = await self._send_request(
                    self.session.read_resource(AnyUrl(uri))
                )
            if not result.contents:
                raise MCPClientError(f"Resource {uri} returned no contents")
            first = result.contents[0]
            text = first.text if isinstance(first, TextResourceContents) else None
            max_bytes = get_settings().mcp_app_resource_max_bytes
            if text is not None and len(text.encode("utf-8")) > max_bytes:
                raise MCPClientError(
                    f"Resource {uri} exceeds the configured maximum of "
                    f"{max_bytes} bytes"
                )
            raw_meta = first.meta
            return {
                "uri": str(first.uri),
                "text": text,
                "mime_type": first.mimeType,
                "meta": raw_meta if isinstance(raw_meta, dict) else None,
            }
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as e:
            raise MCPClientError(
                "Failed to read resource: request timed out after "
                f"{self.tool_call_timeout}s"
            ) from e
        except MCPClientError:
            refused = self._request_refusal.statuses.get("resources/read")
            if refused is None:
                raise
            self._request_refusal.failed_with = refused
            raise MCPClientError(
                f"Resource read failed: the server answered HTTP {refused}"
            ) from None
        except BaseException as e:
            error_msg = _extract_error_message(e) or str(e)
            logger.error(
                f"Failed to read resource {uri} from {self.mcp_server.name}: "
                f"{error_msg}"
            )
            raise MCPClientError(f"Resource read failed: {error_msg}") from e

    def request_disconnect(self) -> None:
        """Start closing without waiting; the host unwinds on its own.

        Synchronous on purpose: a caller whose cleanup budget is already
        spent is cut off at its first await, and the connection must still
        end. ``disconnect()`` afterwards only waits.
        """
        if self._host is not None:
            self._host.request_stop()

    async def disconnect(self) -> None:
        """Close the connection: the host leaves the SDK contexts; this waits.

        Safe from any task and under cancellation: the host unwinds on its
        own once asked, so a caller that stops waiting does not leak it.
        """
        host = self._host
        self._host = None
        self.session = None
        if host is None:
            return
        await host.stop(MCP_DISCONNECT_TIMEOUT_SECONDS)
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
