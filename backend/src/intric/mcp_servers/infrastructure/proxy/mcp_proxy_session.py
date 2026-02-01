"""
MCPProxySession - Session-scoped proxy for multiple MCP servers.

Provides:
- Lazy connection management (connect on first tool call)
- Connection caching within session
- Unified tool interface for LLM
- Automatic cleanup on session end
"""

import asyncio
import re
import time
from typing import Any
from uuid import UUID

from intric.main.logging import get_logger
from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.mcp_servers.infrastructure.client.mcp_client import MCPClient

logger = get_logger(__name__)


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
        self.mcp_servers = mcp_servers
        self.auth_credentials_map = auth_credentials_map or {}

        # Lazy connection cache: server_id -> MCPClient (connected)
        self._clients: dict[UUID, MCPClient] = {}
        self._connection_locks: dict[UUID, asyncio.Lock] = {}

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
                self._tools_for_llm.append({
                    "type": "function",
                    "function": {
                        "name": prefixed_name,
                        "description": tool.description or f"Tool from {server.name}",
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    },
                })

        logger.debug(
            f"[MCPProxy] Built registry with {len(self._tool_registry)} tools "
            f"from {len(self.mcp_servers)} servers"
        )

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

    async def _get_or_create_client(self, server: MCPServer) -> MCPClient:
        """
        Get existing client or create new connection (lazy).

        Thread-safe via per-server locks.

        Args:
            server: MCP server to connect to

        Returns:
            Connected MCPClient instance

        Raises:
            MCPClientError: If connection fails
        """
        server_id = server.id

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

        logger.debug(
            f"[MCPProxy] Calling {original_tool_name} on '{server.name}'"
        )

        # Get or create connection (lazy)
        client = await self._get_or_create_client(server)

        # Execute tool with timing
        start_time = time.perf_counter()
        result = await client.call_tool(original_tool_name, arguments)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        is_error = result.get("is_error", False)
        status = "ERROR" if is_error else "OK"
        logger.debug(
            f"[MCPProxy] {original_tool_name} completed in {elapsed_ms:.0f}ms [{status}]"
        )

        return result

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
        logger.debug(
            f"[MCPProxy] Executing {len(tool_calls)} tool(s): {tool_names}"
        )
        total_start = time.perf_counter()

        # First, identify all servers we need to connect to (by ID to avoid hashability issues)
        servers_needed: dict[UUID, MCPServer] = {}
        for tool_name, _ in tool_calls:
            if tool_name in self._tool_registry:
                server, _ = self._tool_registry[tool_name]
                servers_needed[server.id] = server

        # Connect to all needed servers in parallel (lazy - only if not already connected)
        if servers_needed:
            connect_tasks = [
                self._get_or_create_client(server)
                for server in servers_needed.values()
            ]
            await asyncio.gather(*connect_tasks, return_exceptions=True)

        # Execute all tool calls in parallel
        async def execute_single(tool_name: str, arguments: dict) -> dict[str, Any]:
            try:
                return await self.call_tool(tool_name, arguments)
            except Exception as e:
                logger.error(f"[MCPProxy] Tool {tool_name} failed: {e}")
                return {
                    "content": [{"type": "text", "text": f"Error executing tool: {str(e)}"}],
                    "is_error": True,
                }

        results = await asyncio.gather(*[
            execute_single(name, args) for name, args in tool_calls
        ])

        total_elapsed_ms = (time.perf_counter() - total_start) * 1000
        error_count = sum(1 for r in results if r.get("is_error"))
        logger.debug(
            f"[MCPProxy] Completed {len(tool_calls)} tool(s) in {total_elapsed_ms:.0f}ms "
            f"({error_count} errors)"
        )

        return list(results)

    async def close(self):
        """Close all connections."""
        if not self._clients:
            return

        for server_id, client in self._clients.items():
            try:
                await client.disconnect()
            except Exception as e:
                logger.debug(f"[MCPProxy] Error disconnecting from {server_id}: {e}")

        connection_count = len(self._clients)
        self._clients.clear()
        logger.debug(f"[MCPProxy] Session closed, {connection_count} connection(s) cleaned up")

    async def __aenter__(self):
        """Async context manager entry - no connections yet (lazy)."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close all connections."""
        await self.close()
