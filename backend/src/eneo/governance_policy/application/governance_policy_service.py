# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import TYPE_CHECKING
from uuid import UUID

from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyCompletionModel,
    PolicyMcpServer,
    PolicyScope,
)
from eneo.governance_policy.domain.governance_policy_repo import (
    GovernancePolicyRepo,
)
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.roles.permissions import Permission, validate_permission
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from eneo.mcp_servers.application.mcp_server_settings_service import (
        MCPServerSettingsService,
    )
    from eneo.model_providers.infrastructure.model_provider_repository import (
        ModelProviderRepository,
    )
    from eneo.prompt_library.application.prompt_library_service import (
        PromptLibraryService,
    )


class GovernancePolicyService:
    def __init__(
        self,
        user: UserInDB,
        repo: GovernancePolicyRepo,
        completion_model_crud_service: "CompletionModelCRUDService",
        mcp_server_settings_service: "MCPServerSettingsService",
        prompt_library_service: "PromptLibraryService",
        model_provider_repository: "ModelProviderRepository",
    ) -> None:
        self.user = user
        self.repo = repo
        self.completion_model_crud_service = completion_model_crud_service
        self.mcp_server_settings_service = mcp_server_settings_service
        self.prompt_library_service = prompt_library_service
        self.model_provider_repository = model_provider_repository

    async def get_policy(self) -> GovernancePolicy:
        """Get the tenant's policy, auto-creating an empty one if none exists.

        An auto-created empty policy has all `*_restriction_enabled=False`
        which means no user-facing change — safe to do lazily on first read.
        """
        validate_permission(self.user, Permission.ADMIN)
        # Today the admin surface manages a single scope. A second scope would
        # turn this into a per-scope lookup driven by the request.
        scope = PolicyScope.PERSONAL_DEFAULT_ASSISTANT
        existing = await self.repo.get_by_tenant(self.user.tenant_id, scope=scope)
        if existing is not None:
            return existing
        return await self.repo.create_empty(self.user.tenant_id, scope=scope)

    async def get_policy_for_update(self) -> GovernancePolicy:
        validate_permission(self.user, Permission.ADMIN)
        scope = PolicyScope.PERSONAL_DEFAULT_ASSISTANT
        policy = await self.repo.get_by_tenant_for_update(
            self.user.tenant_id, scope=scope
        )
        if policy is None:
            await self.repo.create_empty(self.user.tenant_id, scope=scope)
            policy = await self.repo.get_by_tenant_for_update(
                self.user.tenant_id, scope=scope
            )
            assert policy is not None
        return policy

    async def update_policy(
        self,
        *,
        models_restriction: (
            tuple[bool, list[PolicyCompletionModel], list[UUID]] | None
        ) = None,
        mcp_restriction: (tuple[bool, list[PolicyMcpServer], list[UUID]] | None) = None,
        prompt_enforcement: tuple[bool, UUID | None] | None = None,
    ) -> GovernancePolicy:
        policy = await self.get_policy_for_update()

        if models_restriction is not None:
            enabled, models, provider_ids = models_restriction
            if enabled:
                if models:
                    await self._validate_models_belong_to_tenant(models)
                if provider_ids:
                    await self._validate_providers_belong_to_tenant(provider_ids)
            policy.set_models_restriction(
                enabled=enabled, models=models, provider_ids=provider_ids
            )

        if mcp_restriction is not None:
            enabled, servers, disabled_tool_ids = mcp_restriction
            if enabled and servers:
                await self._validate_mcp_servers_and_tools(servers, disabled_tool_ids)
            policy.set_mcp_restriction(
                enabled=enabled,
                servers=servers,
                disabled_tool_ids=disabled_tool_ids,
            )

        if prompt_enforcement is not None:
            enabled, prompt_id = prompt_enforcement
            if enabled and prompt_id is not None:
                await self._validate_prompt_belongs_to_tenant(prompt_id)
            policy.set_prompt_enforcement(enabled=enabled, prompt_library_id=prompt_id)

        return await self.repo.save(policy, updated_by_user_id=self.user.id)

    async def _validate_providers_belong_to_tenant(
        self, provider_ids: list[UUID]
    ) -> None:
        tenant_providers = await self.model_provider_repository.all(active_only=False)
        accessible = {p.id for p in tenant_providers}
        for pid in provider_ids:
            if pid not in accessible:
                raise BadRequestException(
                    f"Model provider {pid} is not configured for this tenant"
                )

    async def _validate_models_belong_to_tenant(
        self, models: list[PolicyCompletionModel]
    ) -> None:
        tenant_models = (
            await self.completion_model_crud_service.get_available_completion_models()
        )
        accessible = {m.id for m in tenant_models if m.can_access}
        for m in models:
            if m.completion_model_id not in accessible:
                raise BadRequestException(
                    f"Completion model {m.completion_model_id} is not "
                    "accessible to this tenant"
                )

    async def _validate_mcp_servers_and_tools(
        self, servers: list[PolicyMcpServer], disabled_tool_ids: list[UUID]
    ) -> None:
        tenant_servers = (
            await self.mcp_server_settings_service.get_available_mcp_servers()
        )
        enabled_servers = [s for s in tenant_servers if s.is_enabled]
        enabled_ids = {s.id for s in enabled_servers}
        selected_ids: set[UUID] = set()
        for entry in servers:
            if entry.mcp_server_id not in enabled_ids:
                raise BadRequestException(
                    f"MCP server {entry.mcp_server_id} is not enabled for this tenant"
                )
            selected_ids.add(entry.mcp_server_id)
        # Disabled tools must belong to a selected server — anything else is a
        # stale or cross-tenant reference.
        selectable_tool_ids = {
            tool.id
            for server in enabled_servers
            if server.id in selected_ids
            for tool in server.tools
        }
        for tool_id in disabled_tool_ids:
            if tool_id not in selectable_tool_ids:
                raise BadRequestException(
                    f"MCP tool {tool_id} does not belong to an allowed server"
                )

    async def _validate_prompt_belongs_to_tenant(self, prompt_id: UUID) -> None:
        # get_entry already enforces tenant-scope + admin-permission, and
        # raises NotFoundException for cross-tenant access (translates to 404).
        # We rebrand it here as a 400 because the issue is request-level, not
        # an unknown resource.
        try:
            await self.prompt_library_service.get_entry(prompt_id)
        except NotFoundException:
            raise BadRequestException(
                f"Prompt library entry {prompt_id} not found in this tenant"
            )
