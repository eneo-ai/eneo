import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from eneo.main.exceptions import NameCollisionException, UnauthorizedException
from eneo.main.models import NOT_PROVIDED, NotProvided
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCP_TOOL_CATALOG_DEFAULT_MAX_BYTES,
    MCP_TOOL_CATALOG_DEFAULT_MAX_COUNT,
    MCP_TOOL_DEFINITION_DEFAULT_MAX_BYTES,
    MCPAuthScope,
    MCPExchangeProtocol,
    MCPServer,
    MCPServerTool,
)
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPClientError,
)
from eneo.mcp_servers.infrastructure.identity_headers import build_identity_headers
from eneo.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from eneo.mcp_servers.application.mcp_token_broker import MCPTokenBroker
    from eneo.mcp_servers.domain.repositories.mcp_server_repo import (
        MCPServerRepository,
    )
    from eneo.mcp_servers.domain.repositories.mcp_server_tool_repo import (
        MCPServerToolRepository,
    )
    from eneo.mcp_servers.infrastructure.repo_impl.chat_session_mcp_state_repo_impl import (
        ChatSessionMcpStateRepo,
    )
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from eneo.settings.encryption_service import EncryptionService
    from eneo.users.user import UserInDB

logger = logging.getLogger(__name__)


@dataclass
class ConnectionResult:
    """Result of MCP server connection attempt."""

    success: bool
    tools_discovered: int = 0
    error_message: str | None = None


@dataclass
class MCPServerCreateResult:
    """Result of MCP server creation including connection status."""

    server: MCPServer
    connection: ConnectionResult


@dataclass
class MCPServerUpdateResult:
    """Result of MCP server update including optional connection status."""

    server: MCPServer
    connection: ConnectionResult | None = None


@dataclass
class ToolChange:
    """Represents a change detected during tool sync."""

    tool: MCPServerTool
    change_type: str  # "new", "changed", "removed", "unchanged"
    current_description: str | None = None
    current_input_schema: dict[str, Any] | None = None
    pending_description: str | None = None
    pending_input_schema: dict[str, Any] | None = None


@dataclass
class ToolSyncResult:
    """Result of tool sync with changeset for review."""

    connection: ConnectionResult
    new_tools: list[ToolChange] = field(default_factory=lambda: [])
    changed_tools: list[ToolChange] = field(default_factory=lambda: [])
    removed_tools: list[ToolChange] = field(default_factory=lambda: [])
    unchanged_count: int = 0

    @property
    def has_pending_changes(self) -> bool:
        return bool(self.new_tools or self.changed_tools or self.removed_tools)


class MCPServerService:
    """Service for managing global MCP server catalog (admin only)."""

    def __init__(
        self,
        mcp_server_repo: "MCPServerRepository",
        mcp_server_tool_repo: "MCPServerToolRepository",
        user: "UserInDB",
        mcp_state_repo: "ChatSessionMcpStateRepo",
        encryption_service: "EncryptionService | None" = None,
        mcp_token_broker: "MCPTokenBroker | None" = None,
    ):
        super().__init__()
        self.repo = mcp_server_repo
        self.tool_repo = mcp_server_tool_repo
        self.user = user
        self.mcp_state_repo = mcp_state_repo
        self.encryption_service = encryption_service
        self.mcp_token_broker = mcp_token_broker

    # Keys in http_auth_config_schema that contain secrets
    _SECRET_KEYS = ("token",)

    async def _get_server_for_tenant(self, mcp_server_id: UUID) -> MCPServer:
        """Fetch an MCP server and verify it belongs to the current user's tenant."""
        server = await self.repo.one(id=mcp_server_id)
        if server.tenant_id != self.user.tenant_id:
            raise UnauthorizedException("MCP server not accessible")
        return server

    def _encrypt_auth_config(
        self, config: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Encrypt sensitive values in auth config before storing."""
        if (
            not config
            or not self.encryption_service
            or not self.encryption_service.is_active()
        ):
            return config

        encrypted = dict(config)
        for key in self._SECRET_KEYS:
            if key in encrypted and encrypted[key]:
                encrypted[key] = self.encryption_service.encrypt(encrypted[key])
        return encrypted

    def _decrypt_auth_config(
        self, config: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Decrypt sensitive values in auth config for use."""
        if not config:
            return config

        decrypted = dict(config)
        for key in self._SECRET_KEYS:
            if key in decrypted and decrypted[key]:
                if self.encryption_service and self.encryption_service.is_encrypted(
                    decrypted[key]
                ):
                    decrypted[key] = self.encryption_service.decrypt(decrypted[key])
        return decrypted

    async def get_mcp_servers(self, tags: list[str] | None = None) -> list[MCPServer]:
        """Get all MCP servers from global catalog with optional tag filtering."""
        if tags:
            return await self.repo.query(tags=tags, tenant_id=self.user.tenant_id)
        return await self.repo.query(tenant_id=self.user.tenant_id)

    async def get_mcp_server(self, mcp_server_id: UUID) -> MCPServer:
        """Get a single MCP server by ID."""
        server = await self.repo.one(id=mcp_server_id)
        if server.tenant_id != self.user.tenant_id:
            from eneo.main.exceptions import UnauthorizedException

            raise UnauthorizedException("MCP server not accessible")
        return server

    @validate_permissions(Permission.ADMIN)
    async def create_mcp_server(
        self,
        name: str,
        http_url: str,
        http_auth_type: str = "none",
        description: str | None = None,
        http_auth_config_schema: dict[str, Any] | None = None,
        forward_identity: bool = False,
        tool_catalog_max_count: int = MCP_TOOL_CATALOG_DEFAULT_MAX_COUNT,
        tool_catalog_max_bytes: int = MCP_TOOL_CATALOG_DEFAULT_MAX_BYTES,
        tool_definition_max_bytes: int = MCP_TOOL_DEFINITION_DEFAULT_MAX_BYTES,
        tags: list[str] | None = None,
        icon_url: str | None = None,
        documentation_url: str | None = None,
        security_classification: "SecurityClassification | None" = None,
        auth_scope: MCPAuthScope = "static_bearer",
        expected_idp_issuer: str | None = None,
        target_resource_or_scope: str | None = None,
        exchange_protocol: MCPExchangeProtocol = "auto",
    ) -> MCPServerCreateResult:
        """Create a new MCP server for the tenant (admin only, uses Streamable HTTP transport).

        Validates connection BEFORE saving to database to avoid orphaned entries.
        """
        http_url = str(http_url)
        if icon_url is not None:
            icon_url = str(icon_url)
        if documentation_url is not None:
            documentation_url = str(documentation_url)

        # Create domain object (not saved yet)
        mcp_server = MCPServer(
            tenant_id=self.user.tenant_id,
            name=name,
            http_url=http_url,
            http_auth_type=http_auth_type,
            description=description,
            http_auth_config_schema=http_auth_config_schema,
            forward_identity=forward_identity,
            tool_catalog_max_count=tool_catalog_max_count,
            tool_catalog_max_bytes=tool_catalog_max_bytes,
            tool_definition_max_bytes=tool_definition_max_bytes,
            tags=tags,
            icon_url=icon_url,
            documentation_url=documentation_url,
            security_classification=security_classification,
            auth_scope=auth_scope,
            expected_idp_issuer=expected_idp_issuer,
            target_resource_or_scope=target_resource_or_scope,
            exchange_protocol=exchange_protocol,
        )

        # Test connection FIRST with plaintext credentials before saving to database
        auth_credentials = http_auth_config_schema if http_auth_config_schema else None
        tools, connection_result = await self._test_connection_and_discover_tools(
            mcp_server, auth_credentials
        )

        # Only save to database if connection succeeded
        if not connection_result.success:
            # Return error without saving - let user fix the URL
            return MCPServerCreateResult(
                server=mcp_server, connection=connection_result
            )

        # Encrypt credentials before saving to database (skip if auth type is "none")
        if http_auth_type != "none" and http_auth_config_schema:
            mcp_server.http_auth_config_schema = self._encrypt_auth_config(
                http_auth_config_schema
            )
        else:
            mcp_server.http_auth_config_schema = None

        # Connection succeeded - save to database
        try:
            mcp_server = await self.repo.add(mcp_server)
        except IntegrityError as e:
            raise NameCollisionException(
                "An MCP server with this name already exists."
            ) from e

        # Save discovered tools
        for tool_def in tools:
            tool = MCPServerTool(
                mcp_server_id=mcp_server.id,
                name=tool_def["name"],
                title=tool_def.get("title"),
                description=tool_def.get("description"),
                input_schema=tool_def.get("input_schema"),
                is_enabled_by_default=True,
            )
            await self.tool_repo.upsert_by_server_and_name(tool)

        connection_result.tools_discovered = len(tools)
        return MCPServerCreateResult(server=mcp_server, connection=connection_result)

    @validate_permissions(Permission.ADMIN)
    async def update_mcp_server(
        self,
        mcp_server_id: UUID,
        name: str | None = None,
        http_url: str | None = None,
        http_auth_type: str | None = None,
        description: str | None = None,
        http_auth_config_schema: dict[str, Any] | None = None,
        forward_identity: bool | None = None,
        tool_catalog_max_count: int | None = None,
        tool_catalog_max_bytes: int | None = None,
        tool_definition_max_bytes: int | None = None,
        tags: list[str] | None = None,
        icon_url: str | None = None,
        documentation_url: str | None = None,
        security_classification: "SecurityClassification | NotProvided | None" = NOT_PROVIDED,
        auth_scope: MCPAuthScope | None = None,
        expected_idp_issuer: "str | NotProvided | None" = NOT_PROVIDED,
        target_resource_or_scope: "str | NotProvided | None" = NOT_PROVIDED,
        exchange_protocol: MCPExchangeProtocol | None = None,
    ) -> MCPServerUpdateResult:
        """Update an MCP server in global catalog (admin only, uses Streamable HTTP transport).

        Validates connection before saving when connection-affecting fields
        (URL, authentication, credentials, identity forwarding) change.
        Returns MCPServerUpdateResult with connection info when validation occurs.
        """
        mcp_server = await self._get_server_for_tenant(mcp_server_id)
        # Track whether connection-affecting fields are actually changing
        url_changed = http_url is not None and str(http_url) != mcp_server.http_url
        auth_type_changed = (
            http_auth_type is not None and http_auth_type != mcp_server.http_auth_type
        )
        credentials_changed = http_auth_config_schema is not None
        identity_mode_changed = (
            forward_identity is not None
            and forward_identity != mcp_server.forward_identity
        )
        # Cached exchanged tokens are keyed on audience + issuer; any change
        # to these fields invalidates them.
        cache_affecting_changed = (
            url_changed
            or (auth_scope is not None and auth_scope != mcp_server.auth_scope)
            or (
                not isinstance(expected_idp_issuer, NotProvided)
                and expected_idp_issuer != mcp_server.expected_idp_issuer
            )
            or (
                not isinstance(target_resource_or_scope, NotProvided)
                and target_resource_or_scope != mcp_server.target_resource_or_scope
            )
            or (
                exchange_protocol is not None
                and exchange_protocol != mcp_server.exchange_protocol
            )
        )

        # Apply changes to domain object
        if name is not None:
            mcp_server.name = name
        if http_url is not None:
            mcp_server.http_url = str(http_url)
        if http_auth_type is not None:
            mcp_server.http_auth_type = http_auth_type
            # If switching to "none", clear credentials
            if http_auth_type == "none":
                mcp_server.http_auth_config_schema = None
        if description is not None:
            mcp_server.description = description
        if forward_identity is not None:
            mcp_server.forward_identity = forward_identity
        if tool_catalog_max_count is not None:
            mcp_server.tool_catalog_max_count = tool_catalog_max_count
        if tool_catalog_max_bytes is not None:
            mcp_server.tool_catalog_max_bytes = tool_catalog_max_bytes
        if tool_definition_max_bytes is not None:
            mcp_server.tool_definition_max_bytes = tool_definition_max_bytes
        if tags is not None:
            mcp_server.tags = tags
        if icon_url is not None:
            mcp_server.icon_url = str(icon_url)
        if documentation_url is not None:
            mcp_server.documentation_url = str(documentation_url)
        if not isinstance(security_classification, NotProvided):
            mcp_server.security_classification = security_classification
        if auth_scope is not None:
            previous_scope = mcp_server.auth_scope
            mcp_server.auth_scope = auth_scope
            # SSO scopes (per_user / per_tenant) authenticate via token-exchange
            # at call time; any previously stored static bearer is dead weight
            # and a stale-secret risk. Clear it on transition into SSO.
            if (
                auth_scope in ("per_user", "per_tenant")
                and previous_scope == "static_bearer"
            ):
                mcp_server.http_auth_config_schema = None
        if not isinstance(expected_idp_issuer, NotProvided):
            mcp_server.expected_idp_issuer = expected_idp_issuer
        if not isinstance(target_resource_or_scope, NotProvided):
            mcp_server.target_resource_or_scope = target_resource_or_scope
        if exchange_protocol is not None:
            mcp_server.exchange_protocol = exchange_protocol

        # Validate connection before saving when connection config changes.
        # SSO scopes are excluded: the broker exchanges a fresh token per user
        # at call time, so there are no admin-time credentials to test with.
        if mcp_server.auth_scope in ("per_user", "per_tenant"):
            pass
        elif (
            url_changed
            or auth_type_changed
            or credentials_changed
            or identity_mode_changed
        ):
            if mcp_server.http_auth_type == "none":
                test_credentials = None
            elif http_auth_config_schema is not None:
                # New credentials provided — use plaintext for test
                test_credentials = http_auth_config_schema
            else:
                # Connection mode changed with existing credentials — decrypt them
                test_credentials = self._decrypt_auth_config(
                    mcp_server.http_auth_config_schema
                )

            (
                discovered_tools,
                connection_result,
            ) = await self._test_connection_and_discover_tools(
                mcp_server, test_credentials
            )
            if not connection_result.success:
                return MCPServerUpdateResult(
                    server=mcp_server, connection=connection_result
                )
            if identity_mode_changed and not mcp_server.forward_identity:
                try:
                    await self._sync_discovered_tool_definitions(
                        mcp_server, discovered_tools
                    )
                except Exception as exc:
                    logger.exception(
                        "Failed to reconcile the anonymous MCP tool catalog for %s",
                        mcp_server.name,
                    )
                    return MCPServerUpdateResult(
                        server=mcp_server,
                        connection=ConnectionResult(
                            success=False,
                            error_message=(
                                f"The anonymous tool catalog could not be saved: {exc}"
                            ),
                        ),
                    )

        # Encrypt and apply new credentials after validation passes
        if http_auth_config_schema is not None and mcp_server.http_auth_type != "none":
            mcp_server.http_auth_config_schema = self._encrypt_auth_config(
                http_auth_config_schema
            )
        if identity_mode_changed:
            mcp_server.identity_policy_generation += 1

        try:
            mcp_server = await self.repo.update(mcp_server)
            if identity_mode_changed:
                await self.mcp_state_repo.delete_for_server(mcp_server.id)
        except IntegrityError as e:
            raise NameCollisionException(
                "An MCP server with this name already exists."
            ) from e
        if cache_affecting_changed and self.mcp_token_broker is not None:
            await self.mcp_token_broker.purge_cache_for_server(mcp_server.id)
        return MCPServerUpdateResult(server=mcp_server)

    @validate_permissions(Permission.ADMIN)
    async def delete_mcp_server(self, mcp_server_id: UUID) -> None:
        """Delete an MCP server from global catalog (admin only)."""
        await self._get_server_for_tenant(mcp_server_id)
        await self.repo.delete(id=mcp_server_id)

    async def _test_connection_and_discover_tools(
        self,
        mcp_server: MCPServer,
        auth_credentials: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> tuple[list[dict[str, Any]], ConnectionResult]:
        """
        Test connection to MCP server and discover tools WITHOUT saving to database.

        Used during server creation to validate the URL before persisting.

        Args:
            mcp_server: MCP server to test (not yet saved to DB)
            auth_credentials: Optional authentication credentials
            timeout: Connection timeout in seconds (default 10s for fast feedback)

        Returns:
            Tuple of (list of tool definitions as dicts, connection result)
        """
        try:
            logger.info(
                f"Testing connection to MCP server: {mcp_server.name} at {mcp_server.http_url}"
            )

            # Connect with shorter timeout for faster feedback during creation.
            # The acting admin's identity rides along so a forward_identity
            # server sees the same headers here as on runtime chat requests;
            # the client drops them unless the server opted in.
            async with MCPClient(
                mcp_server,
                auth_credentials,
                timeout=timeout,
                identity_headers=build_identity_headers(self.user, None),
            ) as client:
                tool_defs = await client.list_tools()

            logger.info(
                f"Connection successful - discovered {len(tool_defs)} tools from {mcp_server.name}"
            )
            return tool_defs, ConnectionResult(
                success=True, tools_discovered=len(tool_defs)
            )

        except MCPClientError as e:
            error_msg = str(e)
            if "Connection refused" in error_msg:
                error_msg = f"Could not connect to {mcp_server.http_url}. Please verify the URL and that the server is running."
            elif "timed out" in error_msg.lower():
                error_msg = f"Connection to {mcp_server.http_url} timed out. The server may be slow or unreachable."
            logger.warning(f"Connection test failed for {mcp_server.name}: {e}")
            return [], ConnectionResult(success=False, error_message=error_msg)

        except Exception as e:
            logger.error(
                f"Unexpected error testing connection to {mcp_server.name}: {e}"
            )
            return [], ConnectionResult(
                success=False, error_message=f"Connection failed: {e}"
            )

    async def discover_and_sync_tools(
        self, mcp_server: MCPServer, auth_credentials: dict[str, str] | None = None
    ) -> ToolSyncResult:
        """
        Connect to MCP server, discover tools, and detect changes.

        New tools and changes are stored as pending and require admin approval
        before becoming active. This prevents a compromised MCP server from
        silently injecting malicious tool definitions.

        Returns:
            ToolSyncResult with categorized changes for review
        """
        try:
            logger.info(f"Discovering tools for MCP server: {mcp_server.name}")

            # Connect to MCP server and list tools. As with connection
            # validation, discovery carries the acting admin's identity so an
            # opted-in server exposes the same tool set it will serve at
            # runtime; the client drops the headers unless the server opted in.
            async with MCPClient(
                mcp_server,
                auth_credentials,
                identity_headers=build_identity_headers(self.user, None),
            ) as client:
                tool_defs = await client.list_tools()

            logger.info(f"Discovered {len(tool_defs)} tools from {mcp_server.name}")

            result = await self._sync_discovered_tool_definitions(mcp_server, tool_defs)

            logger.info(
                f"Sync for {mcp_server.name}: "
                f"{len(result.new_tools)} new, {len(result.changed_tools)} changed, "
                f"{len(result.removed_tools)} removed, {result.unchanged_count} unchanged"
            )
            return result

        except MCPClientError as e:
            error_msg = str(e)
            if "Connection refused" in error_msg:
                error_msg = f"Could not connect to {mcp_server.http_url}. Please verify the URL and that the server is running."
            elif "timed out" in error_msg.lower():
                error_msg = f"Connection to {mcp_server.http_url} timed out. The server may be slow or unreachable."
            logger.warning(f"Failed to discover tools for {mcp_server.name}: {e}")
            return ToolSyncResult(
                connection=ConnectionResult(success=False, error_message=error_msg)
            )

        except Exception as e:
            logger.error(f"Failed to discover tools for {mcp_server.name}: {e}")
            return ToolSyncResult(
                connection=ConnectionResult(
                    success=False, error_message=f"Failed to connect: {e}"
                )
            )

    async def _sync_discovered_tool_definitions(
        self, mcp_server: MCPServer, tool_defs: list[dict[str, Any]]
    ) -> ToolSyncResult:
        """Reconcile one validated remote catalog through the bounded owner.

        New definitions and approved-definition drift are staged atomically by
        the repository's projected-union transaction. Availability changes and
        display titles are applied only after that bounded operation succeeds.
        """
        existing_tools = await self.tool_repo.by_server(mcp_server.id)
        existing_by_name = {tool.name: tool for tool in existing_tools}
        remote_names = {tool_def["name"] for tool_def in tool_defs}

        observations = [
            MCPServerTool.pending_discovery(
                mcp_server_id=mcp_server.id,
                name=tool_def["name"],
                title=tool_def.get("title"),
                description=tool_def.get("description"),
                input_schema=tool_def.get("input_schema"),
            )
            for tool_def in tool_defs
            if (
                tool_def["name"] not in existing_by_name
                or (
                    not existing_by_name[tool_def["name"]].requires_approval
                    and existing_by_name[tool_def["name"]].has_definition_drift(
                        description=tool_def.get("description"),
                        input_schema=tool_def.get("input_schema"),
                    )
                )
            )
        ]
        staged = await self.tool_repo.stage_observed(observations)
        staged_by_name = {tool.name: tool for tool in staged}
        if observations:
            current_tools = await self.tool_repo.by_server(mcp_server.id)
        else:
            current_tools = existing_tools
        current_by_name = {tool.name: tool for tool in current_tools}

        result = ToolSyncResult(
            connection=ConnectionResult(success=True, tools_discovered=len(tool_defs))
        )
        for tool_def in tool_defs:
            name = tool_def["name"]
            remote_title = tool_def.get("title")
            remote_desc = tool_def.get("description")
            remote_schema = tool_def.get("input_schema")
            previous = existing_by_name.get(name)
            current = current_by_name.get(name) or staged_by_name.get(name)
            if current is None:
                raise RuntimeError(f"Observed MCP tool '{name}' was not persisted")

            if previous is None:
                result.new_tools.append(
                    ToolChange(
                        tool=current,
                        change_type="new",
                        pending_description=current.pending_description,
                        pending_input_schema=current.pending_input_schema,
                    )
                )
                continue

            title_changed = current.title != remote_title
            was_removed = current.removed_from_remote
            if title_changed:
                current.title = remote_title
            if was_removed:
                current.removed_from_remote = False
            if title_changed or was_removed:
                await self.tool_repo.update(current)

            if previous.has_definition_drift(
                description=remote_desc,
                input_schema=remote_schema,
            ):
                result.changed_tools.append(
                    ToolChange(
                        tool=current,
                        change_type="changed",
                        current_description=current.description,
                        current_input_schema=current.input_schema,
                        pending_description=current.pending_description,
                        pending_input_schema=current.pending_input_schema,
                    )
                )
            else:
                result.unchanged_count += 1

        # An identity-scoped catalog is one principal's view. Only an anonymous
        # catalog is a safe availability snapshot for global exposure.
        if not mcp_server.forward_identity:
            for name, current in current_by_name.items():
                if name not in remote_names and not current.removed_from_remote:
                    current.removed_from_remote = True
                    current.requires_approval = True
                    await self.tool_repo.update(current)
                    result.removed_tools.append(
                        ToolChange(
                            tool=current,
                            change_type="removed",
                            current_description=current.description,
                            current_input_schema=current.input_schema,
                        )
                    )

        return result

    @validate_permissions(Permission.ADMIN)
    async def refresh_tools(
        self, mcp_server_id: UUID, auth_credentials: dict[str, str] | None = None
    ) -> ToolSyncResult:
        """
        Manually refresh tools for an MCP server (admin only).

        Detects changes and stores them as pending for review.
        Returns a ToolSyncResult with categorized changes.
        """
        mcp_server = await self._get_server_for_tenant(mcp_server_id)

        # If no explicit credentials provided, decrypt stored ones
        if auth_credentials is None:
            auth_credentials = self._decrypt_auth_config(
                mcp_server.http_auth_config_schema
            )

        return await self.discover_and_sync_tools(mcp_server, auth_credentials)

    @validate_permissions(Permission.ADMIN)
    async def approve_tool_changes(
        self, mcp_server_id: UUID, tool_ids: list[UUID]
    ) -> list[MCPServerTool]:
        """
        Approve pending tool changes (admin only).

        For new/changed tools: pending values become active values.
        For removed tools: tool is deleted from database.
        """
        await self._get_server_for_tenant(mcp_server_id)
        approved_tools: list[MCPServerTool] = []

        for tool_id in tool_ids:
            tool = await self.tool_repo.one(id=tool_id)
            if tool.mcp_server_id != mcp_server_id:
                continue

            if tool.removed_from_remote:
                # Tool was removed from remote — delete it
                await self.tool_repo.delete(id=tool_id)
                continue

            if tool.requires_approval:
                # Promote pending values to active
                if tool.pending_description is not None:
                    tool.description = tool.pending_description
                if tool.pending_input_schema is not None:
                    tool.input_schema = tool.pending_input_schema

                # Clear pending state
                tool.pending_description = None
                tool.pending_input_schema = None
                tool.requires_approval = False

                tool = await self.tool_repo.update(tool)
                approved_tools.append(tool)

        return approved_tools

    @validate_permissions(Permission.ADMIN)
    async def reject_tool_changes(
        self, mcp_server_id: UUID, tool_ids: list[UUID]
    ) -> list[MCPServerTool]:
        """
        Reject pending tool changes (admin only).

        For new tools: tool is deleted (never activated).
        For changed tools: pending values are cleared, active values kept.
        For removed tools: removed flag is cleared, tool stays active.
        """
        await self._get_server_for_tenant(mcp_server_id)
        rejected_tools: list[MCPServerTool] = []

        for tool_id in tool_ids:
            tool = await self.tool_repo.one(id=tool_id)
            if tool.mcp_server_id != mcp_server_id:
                continue

            if (
                tool.requires_approval
                and tool.description is None
                and tool.input_schema is None
            ):
                # New tool that was never active — delete it
                await self.tool_repo.delete(id=tool_id)
                continue

            # Changed or removed tool — clear pending state
            tool.pending_description = None
            tool.pending_input_schema = None
            tool.requires_approval = False
            tool.removed_from_remote = False

            tool = await self.tool_repo.update(tool)
            rejected_tools.append(tool)

        return rejected_tools

    @validate_permissions(Permission.ADMIN)
    async def approve_all_tool_changes(
        self, mcp_server_id: UUID
    ) -> list[MCPServerTool]:
        """Approve all pending tool changes for an MCP server."""
        await self._get_server_for_tenant(mcp_server_id)
        tools = await self.tool_repo.by_server(mcp_server_id)
        pending_ids = [t.id for t in tools if t.requires_approval]
        if not pending_ids:
            return []
        return await self.approve_tool_changes(mcp_server_id, pending_ids)

    @validate_permissions(Permission.ADMIN)
    async def update_tool_default_enabled(
        self, tool_id: UUID, is_enabled: bool
    ) -> MCPServerTool:
        """
        Update the global default enabled status for a tool (admin only).

        Args:
            tool_id: ID of the tool to update
            is_enabled: Whether tool should be enabled by default

        Returns:
            Updated tool
        """
        tool = await self.tool_repo.one(id=tool_id)
        await self._get_server_for_tenant(tool.mcp_server_id)
        tool.is_enabled_by_default = is_enabled
        return await self.tool_repo.update(tool)

    @validate_permissions(Permission.ADMIN)
    async def update_tenant_tool_enabled(
        self, tool_id: UUID, is_enabled: bool
    ) -> MCPServerTool:
        """
        Update tenant-level enablement for a tool (admin only).
        Creates or updates a record in mcp_server_tool_settings.

        Args:
            tool_id: ID of the tool to update
            is_enabled: Whether tool should be enabled for this tenant

        Returns:
            Tool with updated tenant setting applied
        """
        from eneo.database.tables.mcp_server_table import MCPServerToolSettings

        # Verify tool exists and belongs to current tenant
        tool = await self.tool_repo.one(id=tool_id)
        await self._get_server_for_tenant(tool.mcp_server_id)

        # Upsert tenant tool setting
        from datetime import datetime, timezone

        from sqlalchemy.dialects.postgresql import insert

        now = datetime.now(timezone.utc)
        stmt = insert(MCPServerToolSettings).values(
            tenant_id=self.user.tenant_id,
            mcp_server_tool_id=tool_id,
            is_enabled=is_enabled,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "mcp_server_tool_id"],
            set_={"is_enabled": is_enabled, "updated_at": now},
        )

        await self.repo.session.execute(stmt)
        await self.repo.session.commit()

        # Return tool with tenant setting applied
        tool.is_enabled_by_default = is_enabled
        return tool

    async def get_tools_with_tenant_settings(
        self, mcp_server_id: UUID
    ) -> list[MCPServerTool]:
        """
        Get all tools for an MCP server with tenant-level settings applied.

        Args:
            mcp_server_id: ID of the MCP server

        Returns:
            List of tools with effective tenant-level enablement

        Raises:
            NotFoundException: If server doesn't exist
            UnauthorizedException: If server belongs to a different tenant
        """
        # Verify server exists and belongs to current tenant
        await self._get_server_for_tenant(mcp_server_id)

        import sqlalchemy as sa

        from eneo.database.tables.mcp_server_table import MCPServerToolSettings

        # Get all tools for this server
        tools = await self.tool_repo.by_server(mcp_server_id)

        # Load tenant-level tool settings
        tenant_settings_query = sa.select(MCPServerToolSettings).where(
            MCPServerToolSettings.tenant_id == self.user.tenant_id
        )
        tenant_settings_result = await self.repo.session.execute(tenant_settings_query)
        tenant_settings_db = tenant_settings_result.scalars().all()

        # Create map: tool_id -> is_enabled (tenant level)
        tenant_tool_settings = {
            setting.mcp_server_tool_id: setting.is_enabled
            for setting in tenant_settings_db
        }

        # Apply tenant settings to tools
        for tool in tools:
            if tool.id in tenant_tool_settings:
                # Override with tenant setting
                tool.is_enabled_by_default = tenant_tool_settings[tool.id]

        return tools
