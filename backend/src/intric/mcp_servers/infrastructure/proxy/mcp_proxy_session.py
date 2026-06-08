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
from typing import Any
from uuid import UUID

from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPClientError,
)

logger = get_logger(__name__)

_settings = get_settings()
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
    ):
        """
        Initialize proxy session.

        Args:
            mcp_servers: List of MCP servers the assistant has access to
                        (already filtered by tenant/space/assistant hierarchy)
            auth_credentials_map: Map of server_id -> auth credentials
        """
        super().__init__()
        self.mcp_servers = mcp_servers
        self.auth_credentials_map = auth_credentials_map or {}

        # Lazy connection cache: server_id -> MCPClient (connected)
        self._clients: dict[UUID, MCPClient] = {}
        self._connection_locks: dict[UUID, asyncio.Lock] = {}

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
        self._tool_registry: dict[str, tuple[MCPServer, str]] = {}
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

    def _build_tool_registry(self):
        """Build tool registry from DB-stored tool definitions."""
        for server in self.mcp_servers:
            if not server.http_url or not server.tools:
                continue

            server_prefix = self._sanitize_name(server.name.lower())

            for tool in server.tools:
                # Only include enabled tools
                if not tool.is_enabled_by_default:
                    continue
                # Skip new tools that have no active values yet
                if (
                    tool.requires_approval
                    and tool.description is None
                    and tool.input_schema is None
                ):
                    continue

                # Create prefixed tool name: server_name__tool_name
                tool_name_sanitized = self._sanitize_name(tool.name)
                prefixed_name = f"{server_prefix}__{tool_name_sanitized}"

                # Check for collision before registering
                if prefixed_name in self._tool_registry:
                    existing_server, existing_tool = self._tool_registry[prefixed_name]
                    logger.warning(
                        f"[MCPProxy] Tool collision: '{prefixed_name}' from '{server.name}/{tool.name}' "
                        f"skipped (already registered from '{existing_server.name}/{existing_tool}')"
                    )
                    continue  # Skip this tool entirely (no registry, no LLM list)

                # Register tool -> (server, original_name) mapping
                self._tool_registry[prefixed_name] = (server, tool.name)

                # Build OpenAI-format tool definition
                self._tools_for_llm.append(
                    {
                        "type": "function",
                        "function": {
                            "name": prefixed_name,
                            "description": tool.description
                            or f"Tool from {server.name}",
                            "parameters": tool.input_schema
                            or {"type": "object", "properties": {}},
                        },
                    }
                )

        logger.debug(
            f"[MCPProxy] Built registry with {len(self._tool_registry)} tools "
            f"from {len(self.mcp_servers)} servers"
        )

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
        max_chars = _settings.mcp_tool_output_max_chars
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        if len(serialized) <= max_chars:
            return result

        preview = serialized[: max_chars // 2]
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "error": f"Tool output exceeded maximum size of {max_chars} characters",
                            "partial_data_preview": preview,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            "is_error": True,
        }

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

    def get_tool_info(self, prefixed_tool_name: str) -> tuple[str, str] | None:
        """
        Get display-friendly server name and original tool name for a prefixed tool.

        Args:
            prefixed_tool_name: The prefixed tool name (e.g., "local_mcps__resolve_library_id")

        Returns:
            Tuple of (server_display_name, original_tool_name) or None if not found
        """
        if prefixed_tool_name not in self._tool_registry:
            return None
        server, original_tool_name = self._tool_registry[prefixed_tool_name]
        return (server.name, original_tool_name)

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

            # Create new connection with timing
            auth_creds = self.auth_credentials_map.get(server_id, {})
            client = MCPClient(server, auth_creds)

            logger.debug(f"[MCPProxy] Connecting to '{server.name}'...")
            start_time = time.perf_counter()
            await client.connect()
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            self._clients[server_id] = client
            logger.debug(
                f"[MCPProxy] Connected to '{server.name}' in {elapsed_ms:.0f}ms"
            )
            return client

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

        server, original_tool_name = self._tool_registry[tool_name]

        logger.debug(f"[MCPProxy] Calling {original_tool_name} on '{server.name}'")

        if await self._is_circuit_open(server.id):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "External tool service temporarily unavailable. Please retry later.",
                    }
                ],
                "is_error": True,
            }

        if server.id in self._failed_server_ids:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "External tool service temporarily unavailable. Please retry later.",
                    }
                ],
                "is_error": True,
            }

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
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "External tool service temporarily unavailable. Please retry later.",
                    }
                ],
                "is_error": True,
            }

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
            return self._truncate_tool_result(result)
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
                server, _ = self._tool_registry[tool_name]
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
