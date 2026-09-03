"""
MCPProxySession - Session-scoped proxy for multiple MCP servers.

Provides:
- Lazy connection management (connect on first tool call)
- Connection caching within session
- Unified tool interface for LLM
- Automatic cleanup on session end
"""

import asyncio
import json
import re
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.authentication.signed_urls import looks_like_reference_url
from eneo.internal_mcp.constants import FILES_SERVER_NAME
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPClientError,
    validate_tool_catalog,
)

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.repositories.mcp_server_tool_repo import (
        MCPServerToolRepository,
    )

logger = get_logger(__name__)

_settings = get_settings()
MCP_IDENTITY_CATALOG_PREPARATION_TIMEOUT_SECONDS = float(
    _settings.mcp_client_connect_timeout_seconds
    + _settings.mcp_client_list_tools_timeout_seconds
)
_CIRCUIT_BREAKER_STATE: dict[UUID, dict[str, float | int]] = {}
_CIRCUIT_BREAKER_LOCK = asyncio.Lock()


class MCPProxySession:
    """
    Session-scoped proxy for aggregating multiple MCP servers.

    Lifecycle:
    1. Created at start of assistant.ask() or completion request
    2. Tools listed from DB (no connections yet)
    3. On first tool call to a server, connection is established
    4. Connections reused for subsequent calls to same server
    5. All connections closed when session ends (context manager exit)
    """

    def __init__(
        self,
        mcp_servers: list[MCPServer],
        auth_credentials_map: dict[UUID, dict[str, str]] | None = None,
        identity_headers: dict[str, str] | None = None,
        mcp_server_tool_repo: "MCPServerToolRepository | None" = None,
    ):
        """
        Initialize proxy session.

        Args:
            mcp_servers: List of MCP servers the assistant has access to
                        (already filtered by tenant/space/assistant hierarchy)
            auth_credentials_map: Map of server_id -> auth credentials
            identity_headers: Acting user/tenant X-Eneo-* headers, handed to
                every client. Each client forwards them only when its own server
                has ``forward_identity=True`` (per-server PII opt-in).
        """
        super().__init__()
        self.mcp_servers = mcp_servers
        self.auth_credentials_map = auth_credentials_map or {}
        self.identity_headers = identity_headers or {}
        self._mcp_server_tool_repo = mcp_server_tool_repo

        # Lazy connection cache: server_id -> MCPClient (connected)
        self._clients: dict[UUID, MCPClient] = {}
        self._connection_locks: dict[UUID, asyncio.Lock] = {}

        # Servers that pushed a tools/list_changed notification this session.
        # refresh_tools() re-lists them and rebuilds their slice of the
        # registry. Populated by the per-client callback wired in
        # _get_or_create_client; generic — any MCP server can drive it.
        self._dirty_server_ids: set[UUID] = set()

        # Servers that failed to connect or errored mid-session. Tracked instead
        # of dropping clients from the cache: drops would leak the underlying
        # streamablehttp_client whose anyio cancel scope can only be exited from
        # its owner task.
        self._failed_server_ids: set[UUID] = set()

        # The asyncio.Task that opened the first MCP connection. All subsequent
        # connect/disconnect calls must run on this task — the MCP SDK's
        # streamablehttp_client uses anyio cancel scopes that raise RuntimeError
        # if entered and exited from different tasks. Captured lazily on first
        # connect because session construction is synchronous.
        self._owner_task: asyncio.Task[Any] | None = None

        # Build tool registry from DB (no connections needed)
        self._tool_registry: dict[str, tuple[MCPServer, str, str | None]] = {}
        self._tools_for_llm: list[dict[str, Any]] = []
        self._build_tool_registry()

    def _sanitize_name(self, name: str) -> str:
        """
        Sanitize tool/server name for OpenAI pattern ^[a-zA-Z0-9_-]+$

        Args:
            name: Original name

        Returns:
            Sanitized name safe for OpenAI function calling
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        # Ensure it's not empty and doesn't start with a number
        if not sanitized or sanitized[0].isdigit():
            sanitized = "t_" + sanitized
        return sanitized

    @staticmethod
    def _describe_for_llm(
        *,
        server_name: str,
        name: str,
        title: str | None,
        description: str | None,
    ) -> str:
        """Model-facing description, opening with the tool's display name.

        The wire name is a sanitized ``server__tool`` identifier the model must
        emit verbatim, so it cannot double as a label; left to itself the model
        recites that identifier when a user asks what the assistant can do. MCP's
        optional ``title`` is the human-readable name the chat UI already prefers
        for tool-call chips, and the description is the only channel that carries
        it to the model: the OpenAI function schema has no title field.
        """
        base = description or f"Tool from {server_name}"
        if not title or title == name:
            return base
        return f'Display name: "{title}".\n{base}'

    def _register_tool(
        self,
        server: MCPServer,
        server_prefix: str,
        name: str,
        title: str | None,
        description: str | None,
        input_schema: dict[str, Any] | None,
    ) -> str | None:
        """Register one tool into the registry + LLM list.

        Returns the prefixed name on success, or None if the tool was skipped
        because its prefixed name collides with a tool from another server.
        Shared by the DB-backed initial build and the live refresh so prefixing,
        collision handling, and OpenAI-format conversion stay identical.
        """
        tool_name_sanitized = self._sanitize_name(name)
        prefixed_name = f"{server_prefix}__{tool_name_sanitized}"

        # Check for collision before registering. A tool already owned by this
        # same server is not a collision — the refresh path clears a server's
        # entries before re-registering, so any leftover here is another server.
        if prefixed_name in self._tool_registry:
            existing_server, existing_tool, _ = self._tool_registry[prefixed_name]
            logger.warning(
                f"[MCPProxy] Tool collision: '{prefixed_name}' from "
                f"'{server.name}/{name}' skipped (already registered from "
                f"'{existing_server.name}/{existing_tool}')"
            )
            return None

        self._tool_registry[prefixed_name] = (server, name, title)
        self._tools_for_llm.append(
            {
                "type": "function",
                "function": {
                    "name": prefixed_name,
                    "description": self._describe_for_llm(
                        server_name=server.name,
                        name=name,
                        title=title,
                        description=description,
                    ),
                    "parameters": input_schema or {"type": "object", "properties": {}},
                },
            }
        )
        return prefixed_name

    @staticmethod
    def _is_db_tool_enabled(tool: Any) -> bool:
        """Whether a DB-stored tool definition is exposed to the model.

        Admins disable tools per server; we also hide brand-new tools that have
        not been synced with active values yet. Shared by the initial build and
        the live refresh so an admin-disabled tool is never re-exposed when a
        server's tool list is re-listed.
        """
        if not tool.is_enabled_by_default:
            return False
        if getattr(tool, "removed_from_remote", False) is True:
            return False
        if (
            tool.requires_approval
            and tool.description is None
            and tool.input_schema is None
        ):
            return False
        return True

    def _build_tool_registry(self):
        """Build tool registry from DB-stored tool definitions."""
        for server in self.mcp_servers:
            if not server.http_url or not server.tools:
                continue

            server_prefix = self._sanitize_name(server.name.lower())

            for tool in server.tools:
                if not self._is_db_tool_enabled(tool):
                    continue

                self._register_tool(
                    server=server,
                    server_prefix=server_prefix,
                    name=tool.name,
                    # Admin display name wins over the remote-synced title in
                    # every user-facing surface (tool traces, approval cards).
                    title=tool.display_name or tool.title,
                    description=tool.description,
                    input_schema=tool.input_schema,
                )

        logger.debug(
            f"[MCPProxy] Built registry with {len(self._tool_registry)} tools "
            f"from {len(self.mcp_servers)} servers"
        )

    def _rebuild_server_tools(
        self, server: MCPServer, live_tools: list[dict[str, Any]]
    ) -> bool:
        """Replace a server's registry slice with a freshly-listed tool set.

        Used by refresh_tools after a tools/list_changed: drop every prefixed
        name currently owned by this server, then re-register the intersection
        of the live ``list_tools()`` response and the admin-approved DB catalog.
        Definitions always come from the DB: a compromised server must not be
        able to inject a new tool or silently replace an approved tool's schema.
        Progressive discovery still works for previously approved tools that
        were absent from the server's earlier live list. Returns True if the
        server's set of prefixed names changed.
        """
        before = {
            prefixed
            for prefixed, (srv, _, _) in self._tool_registry.items()
            if srv.id == server.id
        }

        # Drop the server's existing entries from both the registry and the
        # LLM-facing list so re-registration starts clean (and stale tools the
        # server no longer exposes disappear).
        for prefixed in before:
            self._tool_registry.pop(prefixed, None)
        self._tools_for_llm = [
            t for t in self._tools_for_llm if t["function"]["name"] not in before
        ]

        approved_tools = {
            tool.name: tool
            for tool in (server.tools or [])
            if self._is_db_tool_enabled(tool)
        }

        server_prefix = self._sanitize_name(server.name.lower())
        after: set[str] = set()
        for live_tool in live_tools:
            db_tool = approved_tools.get(live_tool["name"])
            if db_tool is None:
                logger.warning(
                    "[MCPProxy] Ignoring unapproved live tool '%s/%s'; "
                    "sync and approve it before exposure",
                    server.name,
                    live_tool["name"],
                )
                continue
            prefixed = self._register_tool(
                server=server,
                server_prefix=server_prefix,
                name=db_tool.name,
                title=db_tool.display_name or db_tool.title,
                description=db_tool.description,
                input_schema=db_tool.input_schema,
            )
            if prefixed is not None:
                after.add(prefixed)

        return before != after

    async def _discover_identity_scoped_tools(
        self, server: MCPServer
    ) -> list[dict[str, Any]]:
        auth_credentials = self.auth_credentials_map.get(server.id, {})
        client = MCPClient(
            server,
            auth_credentials,
            identity_headers=self.identity_headers,
        )
        try:
            async with client:
                return await client.list_tools()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[MCPProxy] Failed identity-scoped tool discovery for '%s': %s",
                server.name,
                exc,
            )
            return []

    async def _stage_live_tool_catalog(
        self, server: MCPServer, live_tools: list[dict[str, Any]]
    ) -> bool:
        """Validate and atomically queue new or changed live definitions.

        Runtime discovery remains fail-closed: staging does not add the new
        entity to ``server.tools``, so this request still intersects against
        the pre-approved in-memory catalog.
        """
        try:
            validate_tool_catalog(
                live_tools,
                max_count=server.tool_catalog_max_count,
                max_catalog_bytes=server.tool_catalog_max_bytes,
                max_definition_bytes=server.tool_definition_max_bytes,
            )
        except MCPClientError as exc:
            logger.warning(
                "[MCPProxy] Rejected unsafe live catalog from '%s': %s",
                server.name,
                exc,
            )
            return False

        if self._mcp_server_tool_repo is None or not live_tools:
            return True

        approved_by_name = {tool.name: tool for tool in server.tools}
        staging_candidates: list[dict[str, Any]] = []
        for live_tool in live_tools:
            approved = approved_by_name.get(live_tool["name"])
            if approved is None or (
                not approved.requires_approval
                and approved.has_definition_drift(
                    description=live_tool.get("description"),
                    input_schema=live_tool.get("input_schema"),
                )
            ):
                staging_candidates.append(live_tool)
        if not staging_candidates:
            return True

        observations = [
            MCPServerTool.pending_discovery(
                mcp_server_id=server.id,
                name=live_tool["name"],
                title=live_tool.get("title"),
                description=live_tool.get("description"),
                input_schema=live_tool.get("input_schema"),
            )
            for live_tool in staging_candidates
        ]
        try:
            staged = await self._mcp_server_tool_repo.stage_observed(observations)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[MCPProxy] Failed to stage live catalog from '%s': %s",
                server.name,
                exc,
            )
            return False
        if staged:
            logger.info(
                "[MCPProxy] Staged %d user-observed definition(s) from '%s' "
                "for admin approval",
                len(staged),
                server.name,
            )
        return True

    async def prepare_tools_for_context(self) -> None:
        """Resolve identity-scoped tool catalogs before model exposure.

        The database catalog remains the administrator-approved allowlist. A
        server that receives the acting user's identity may return a narrower
        ``tools/list`` response for that user, so its LLM-facing catalog must
        be the intersection of the two. Global catalogs keep the existing lazy
        connection path.

        Discovery failures fail closed for the affected server: none of its
        administrator-discovered definitions are exposed in this request.
        """
        probe_servers = [
            server for server in self.mcp_servers if server.forward_identity
        ]
        if not probe_servers:
            return

        probe_tasks = [
            asyncio.create_task(self._discover_identity_scoped_tools(server))
            for server in probe_servers
        ]
        pending = set(probe_tasks)
        try:
            _, pending = await asyncio.wait(
                probe_tasks,
                timeout=MCP_IDENTITY_CATALOG_PREPARATION_TIMEOUT_SECONDS,
            )
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        # Apply results only after every probe has closed, and in configured
        # server order rather than network completion order.
        for server, task in zip(probe_servers, probe_tasks, strict=True):
            if task in pending:
                logger.warning(
                    "[MCPProxy] Identity-scoped tool discovery timed out for '%s'",
                    server.name,
                )
                live_tools: list[dict[str, Any]] = []
            else:
                live_tools = task.result()
            catalog_is_safe = await self._stage_live_tool_catalog(server, live_tools)
            self._rebuild_server_tools(server, live_tools if catalog_is_safe else [])

    async def refresh_tools(self, touched_tool_names: list[str] | None = None) -> bool:
        """Re-list tools for servers whose advertised set may have changed.

        Spec-compliant progressive-discovery servers start with a small
        bootstrap tool set (e.g. ``search_tools`` + ``load_tools``) and emit
        ``notifications/tools/list_changed`` once an activation tool reveals
        more. Without re-listing, the model never sees the activated tools and
        loops calling the activator. We refresh the union of:

        * servers that pushed a list_changed notification this session, and
        * servers we just called a tool on (``touched_tool_names``) **that
          advertised tools.listChanged** — the belt-and-suspenders path for when
          the notification did not arrive. Static servers (no listChanged
          capability) are never re-listed here: they keep their DB-synced tool
          set, with no extra tools/list round-trip and no risk of exposing
          server-side tools that were never synced/enabled by an admin.

        Only connected, non-failed servers are re-listed. Must run on the proxy
        session's owner task (it reuses the cached client's session); the agent
        loop calls it right after ``call_tools_parallel``, which connects on
        that same task. Returns True if any server's tool set changed.
        """
        # Dirty servers actually pushed a notification — proof of support. The
        # touched path only adds servers that opted into listChanged.
        target_ids: set[UUID] = set(self._dirty_server_ids)
        for name in touched_tool_names or []:
            entry = self._tool_registry.get(name)
            if entry is None:
                continue
            sid = entry[0].id
            client = self._clients.get(sid)
            if client is not None and client.supports_tools_list_changed:
                target_ids.add(sid)

        # Only servers we hold a live connection to and that have not failed.
        target_ids = {
            sid
            for sid in target_ids
            if sid in self._clients and sid not in self._failed_server_ids
        }
        if not target_ids:
            return False

        servers_by_id = {s.id: s for s in self.mcp_servers}
        changed = False
        for sid in target_ids:
            client = self._clients.get(sid)
            server = servers_by_id.get(sid)
            if client is None or server is None:
                continue
            try:
                live_tools = await client.list_tools()
            except Exception as exc:
                logger.warning(
                    "[MCPProxy] Failed to refresh tools for '%s': %s",
                    server.name,
                    exc,
                )
                continue
            if self._rebuild_server_tools(server, live_tools):
                changed = True
                logger.info(
                    "[MCPProxy] Refreshed tools for '%s' (%d tools now visible)",
                    server.name,
                    sum(
                        1 for srv, _, _ in self._tool_registry.values() if srv.id == sid
                    ),
                )
            client.tools_list_changed_pending = False
            self._dirty_server_ids.discard(sid)

        return changed

    async def _is_circuit_open(self, server_id: UUID) -> bool:
        async with _CIRCUIT_BREAKER_LOCK:
            state = _CIRCUIT_BREAKER_STATE.get(server_id)
            if not state:
                return False
            open_until = float(state.get("open_until", 0.0))
            if open_until <= time.time():
                _CIRCUIT_BREAKER_STATE.pop(server_id, None)
                return False
            return True

    async def _record_failure(self, server_id: UUID) -> None:
        async with _CIRCUIT_BREAKER_LOCK:
            state = _CIRCUIT_BREAKER_STATE.setdefault(
                server_id, {"failures": 0, "open_until": 0.0}
            )
            failures = int(state.get("failures", 0)) + 1
            state["failures"] = failures
            if failures >= _settings.mcp_circuit_breaker_failure_threshold:
                state["open_until"] = (
                    time.time() + _settings.mcp_circuit_breaker_cooldown_seconds
                )

    async def _record_success(self, server_id: UUID) -> None:
        async with _CIRCUIT_BREAKER_LOCK:
            _CIRCUIT_BREAKER_STATE.pop(server_id, None)

    def _mark_server_failed(self, server_id: UUID) -> None:
        """Mark a server unusable for the rest of this session.

        We do NOT drop the client from the cache — that would orphan the
        streamablehttp_client's anyio TaskGroup (its read/write loops keep
        running until __aexit__ is called on the streams context). close()
        will disconnect every cached client at session end, on the owner task.
        """
        self._failed_server_ids.add(server_id)

    def _truncate_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Trim an oversized tool result to the budget instead of failing it.

        Leading content blocks are kept whole until the budget runs out; the
        text block that crosses it is cut mid-text and everything after it is
        dropped. A trailing notice tells the model the output was truncated,
        so e.g. a large page extraction still yields its head as usable,
        citable content rather than an error.
        """
        max_chars = _settings.mcp_tool_output_max_chars
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        if len(serialized) <= max_chars:
            return result

        remaining = max_chars
        kept: list[dict[str, Any]] = []
        dropped = 0
        blocks: list[dict[str, Any]] = result.get("content") or []
        for block in blocks:
            if remaining <= 0:
                dropped += 1
                continue
            size = len(json.dumps(block, ensure_ascii=False, default=str))
            if size <= remaining:
                kept.append(block)
                remaining -= size
            elif block.get("type") == "text":
                text = block.get("text") or ""
                # Serialization overhead (escaping, keys) counts toward the
                # budget, so cut the text to what remains after it.
                overhead = size - len(text)
                kept.append({**block, "text": text[: max(0, remaining - overhead)]})
                remaining = 0
            else:
                # Non-text blocks (images, resources) cannot be kept partially.
                dropped += 1
                remaining = 0
        notice = f"[Tool output truncated at {max_chars} characters"
        if dropped:
            notice += f"; {dropped} content block(s) dropped"
        notice += (
            ". Narrow the request (e.g. fewer URLs or a more specific query) "
            "to fit the limit.]"
        )
        kept.append({"type": "text", "text": notice})
        return {**result, "content": kept}

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        """
        Get all available tools in OpenAI function calling format.

        Returns:
            List of tool definitions ready for LLM consumption
        """
        return self._tools_for_llm

    def get_allowed_tool_names(self) -> set[str]:
        """
        Get set of allowed tool names for security validation.

        Returns:
            Set of prefixed tool names that are allowed
        """
        return set(self._tool_registry.keys())

    def get_tool_count(self) -> int:
        """Get total number of available tools."""
        return len(self._tool_registry)

    def get_tool_info(
        self, prefixed_tool_name: str
    ) -> tuple[str, str, str | None] | None:
        """
        Get display-friendly server name, original tool name, and title for a prefixed tool.

        Returns:
            Tuple of (server_display_name, original_tool_name, title) or None if not found
        """
        if prefixed_tool_name not in self._tool_registry:
            return None
        server, original_tool_name, title = self._tool_registry[prefixed_tool_name]
        return (server.name, original_tool_name, title)

    def _capture_owner_task(self) -> None:
        """Bind this proxy session to the current asyncio.Task on first connect.

        Any later connect or disconnect from a different task would create or
        destroy anyio cancel scopes across task boundaries, which raises
        RuntimeError inside the MCP SDK and silently leaks its TaskGroup
        children (the persistent HTTP read/write loops).
        """
        current = asyncio.current_task()
        if self._owner_task is None:
            self._owner_task = current
        elif current is not self._owner_task:
            logger.error(
                "[MCPProxy] MCP lifecycle call from non-owner task — this would "
                "leak anyio cancel scopes. owner=%s current=%s. Refusing to "
                "connect; the cached client (if any) will be cleaned up by close().",
                self._owner_task,
                current,
            )
            raise MCPClientError(
                "MCP proxy session called from a task other than its owner; "
                "refusing to connect to avoid anyio cancel-scope leak."
            )

    async def _get_or_create_client(self, server: MCPServer) -> MCPClient:
        """
        Get existing client or create new connection (lazy).

        Must run on the proxy session's owner task. Thread-safe via per-server
        locks.

        Args:
            server: MCP server to connect to

        Returns:
            Connected MCPClient instance

        Raises:
            MCPClientError: If connection fails or called from a non-owner task
        """
        server_id = server.id

        self._capture_owner_task()

        # Get or create lock for this server
        if server_id not in self._connection_locks:
            self._connection_locks[server_id] = asyncio.Lock()

        async with self._connection_locks[server_id]:
            # Check if already connected
            if server_id in self._clients:
                logger.debug(
                    f"[MCPProxy] CACHE HIT: Reusing connection to '{server.name}'"
                )
                return self._clients[server_id]

            auth_creds = self.auth_credentials_map.get(server_id, {})
            client = MCPClient(
                server,
                auth_creds,
                on_tools_list_changed=lambda sid=server_id: self._dirty_server_ids.add(
                    sid
                ),
                identity_headers=self.identity_headers,
            )

            logger.debug(f"[MCPProxy] Connecting to '{server.name}'...")
            start_time = time.perf_counter()
            await client.connect()
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            self._clients[server_id] = client
            logger.debug(
                f"[MCPProxy] Connected to '{server.name}' in {elapsed_ms:.0f}ms"
            )
            return client

    def _files_read_file_entry(self) -> tuple[str, str | None] | None:
        """Prefixed name + title of the loopback read_file, when registered.

        Scanned on demand rather than cached: the registry is small and is
        cleared and rebuilt by the live-refresh path, so stored state could go
        stale.
        """
        for prefixed_name, (server, name, title) in self._tool_registry.items():
            if server.name == FILES_SERVER_NAME and name == "read_file":
                return prefixed_name, title
        return None

    def _reference_fallback_hint(
        self, failing_tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """Pointer to the built-in reader for a failed reference-URL call.

        Keys on the argument shape (a signed attachment reference URL), not on
        which server failed: any tool call that carried a reference url can be
        retried against the loopback read_file, which registers exactly when
        reference entries render in the prompt. Empty when no argument is a
        reference, read_file is not registered, or read_file itself failed.
        """
        if not any(
            isinstance(value, str) and looks_like_reference_url(value)
            for value in arguments.values()
        ):
            return ""
        entry = self._files_read_file_entry()
        if entry is None:
            return ""
        prefixed_name, title = entry
        if prefixed_name == failing_tool_name:
            return ""
        display = f' ("{title}")' if title else ""
        return (
            "The attached file itself is still readable: pass the same url "
            f"to the {prefixed_name}{display} tool."
        )

    def _unavailable_result(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Error result for a tool whose server cannot be called right now."""
        text = (
            "External tool service temporarily unavailable. If another "
            "available tool can do the job, use it instead of retrying this "
            "one."
        )
        hint = self._reference_fallback_hint(tool_name, arguments)
        if hint:
            text = f"{text} {hint}"
        return {
            "content": [{"type": "text", "text": text}],
            "is_error": True,
        }

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call a tool by its prefixed name.

        Establishes connection on first call to each server.

        Args:
            tool_name: Prefixed tool name (e.g., "context7__resolve_library_id")
            arguments: Tool arguments

        Returns:
            Tool execution result with structure:
            {
                "content": [{"type": "text", "text": "..."}],
                "is_error": bool
            }

        Raises:
            ValueError: If tool not found in registry
            MCPClientError: If connection or execution fails
        """
        if tool_name not in self._tool_registry:
            raise ValueError(f"Tool not found in proxy registry: {tool_name}")

        server, original_tool_name, _ = self._tool_registry[tool_name]

        logger.debug(f"[MCPProxy] Calling {original_tool_name} on '{server.name}'")

        if await self._is_circuit_open(server.id):
            return self._unavailable_result(tool_name, arguments)

        if server.id in self._failed_server_ids:
            return self._unavailable_result(tool_name, arguments)

        # Use cached client only. Connecting here is unsafe: this method runs
        # under asyncio.gather (see call_tools_parallel), which dispatches each
        # call onto a separate Task. Entering streamablehttp_client's anyio
        # cancel scope from that task would leak when close() runs from the
        # owner task. Pre-connect happens sequentially in call_tools_parallel.
        client = self._clients.get(server.id)
        if client is None:
            logger.warning(
                "[MCPProxy] No connected client for '%s'; pre-connect did not run "
                "or failed",
                server.name,
            )
            self._mark_server_failed(server.id)
            return self._unavailable_result(tool_name, arguments)

        try:
            # Execute tool with timing
            start_time = time.perf_counter()
            result = await client.call_tool(original_tool_name, arguments)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            is_error = result.get("is_error", False)
            status = "ERROR" if is_error else "OK"
            logger.debug(
                f"[MCPProxy] {original_tool_name} completed in {elapsed_ms:.0f}ms [{status}]"
            )
            if is_error:
                await self._record_failure(server.id)
            else:
                await self._record_success(server.id)
            result = self._truncate_tool_result(result)
            if is_error:
                # A tool that failed on a reference URL should not be retried
                # into a loop; appended after truncation so the pointer to the
                # built-in reader survives it.
                hint = self._reference_fallback_hint(tool_name, arguments)
                if hint:
                    blocks: list[Any] = list(result.get("content") or [])
                    blocks.append({"type": "text", "text": hint})
                    result = {**result, "content": blocks}
            return result
        except MCPClientError:
            self._mark_server_failed(server.id)
            await self._record_failure(server.id)
            raise
        except Exception:
            self._mark_server_failed(server.id)
            await self._record_failure(server.id)
            raise

    async def call_tools_parallel(
        self,
        tool_calls: list[tuple[str, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """
        Execute multiple tool calls in parallel.

        Groups calls by server for efficiency, but parallelizes across servers.

        Args:
            tool_calls: List of (tool_name, arguments) tuples

        Returns:
            List of results in same order as input
        """
        if not tool_calls:
            return []

        # Log all tools being called
        tool_names = [name for name, _ in tool_calls]
        logger.debug(f"[MCPProxy] Executing {len(tool_calls)} tool(s): {tool_names}")
        total_start = time.perf_counter()

        # First, identify all servers we need to connect to (by ID to avoid hashability issues)
        servers_needed: dict[UUID, MCPServer] = {}
        for tool_name, _ in tool_calls:
            if tool_name in self._tool_registry:
                server, _, _ = self._tool_registry[tool_name]
                servers_needed[server.id] = server

        # Pre-connect SEQUENTIALLY in this task. Sequential is required:
        # streamablehttp_client uses anyio cancel scopes bound to the connecting
        # task. asyncio.gather would dispatch each connect to its own gather
        # task — close() later runs from the proxy session's owning task and
        # anyio's task-boundary check would silently leak the underlying HTTP
        # read/write loops, creeping CPU toward 100% over the worker's lifetime.
        for server in servers_needed.values():
            if server.id in self._clients or server.id in self._failed_server_ids:
                continue
            try:
                await self._get_or_create_client(server)
            except Exception as exc:
                logger.warning(
                    f"[MCPProxy] Failed to pre-connect to '{server.name}': {exc}"
                )
                self._mark_server_failed(server.id)

        # Execute all tool calls in parallel
        async def execute_single(
            tool_name: str, arguments: dict[str, Any]
        ) -> dict[str, Any]:
            try:
                return await self.call_tool(tool_name, arguments)
            except Exception:
                logger.error(f"[MCPProxy] Tool {tool_name} failed")
                return {
                    "content": [{"type": "text", "text": "Error executing tool."}],
                    "is_error": True,
                }

        results = await asyncio.gather(
            *[execute_single(name, args) for name, args in tool_calls]
        )

        total_elapsed_ms = (time.perf_counter() - total_start) * 1000
        error_count = sum(1 for r in results if r.get("is_error"))
        logger.debug(
            f"[MCPProxy] Completed {len(tool_calls)} tool(s) in {total_elapsed_ms:.0f}ms "
            f"({error_count} errors)"
        )

        return list(results)

    async def close(self):
        """Close all connections.

        Must run on the owner task (the task that opened the connections).
        Calling from a different task triggers anyio's task-boundary check
        inside streamablehttp_client and silently leaks its TaskGroup
        children. We log loudly when that happens so future regressions are
        visible instead of masquerading as a slow CPU climb.
        """
        if not self._clients:
            self._failed_server_ids.clear()
            return

        current = asyncio.current_task()
        if self._owner_task is not None and current is not self._owner_task:
            logger.error(
                "[MCPProxy] close() called from non-owner task — anyio cancel "
                "scopes inside streamablehttp_client will fail to exit and leak. "
                "owner=%s current=%s",
                self._owner_task,
                current,
            )

        # Disconnect in reverse-connect order. Each streamablehttp_client
        # __aenter__ pushes an anyio cancel scope onto this task's scope
        # stack; anyio enforces strict LIFO on __aexit__. Iterating in
        # insertion order would try to exit the first-connected client
        # while later clients' scopes are still on top, which anyio rejects
        # with "Attempted to exit a cancel scope that isn't the current
        # task's current cancel scope" and silently leaks the underlying
        # HTTP read/write TaskGroup children.
        for server_id, client in reversed(self._clients.items()):
            try:
                await client.disconnect()
            except Exception as e:
                logger.debug(f"[MCPProxy] Error disconnecting from {server_id}: {e}")

        connection_count = len(self._clients)
        self._clients.clear()
        self._failed_server_ids.clear()
        logger.debug(
            f"[MCPProxy] Session closed, {connection_count} connection(s) cleaned up"
        )

    async def __aenter__(self):
        """Async context manager entry - no connections yet (lazy)."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - close all connections."""
        await self.close()
