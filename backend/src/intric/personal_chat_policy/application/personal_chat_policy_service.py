# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.exceptions import BadRequestException
from intric.personal_chat_policy.domain.personal_chat_policy import (
    PersonalChatPolicy,
    PolicyCompletionModel,
)
from intric.personal_chat_policy.domain.personal_chat_policy_repo import (
    PersonalChatPolicyRepo,
)
from intric.roles.permissions import Permission, validate_permission
from intric.users.user import UserInDB

if TYPE_CHECKING:
    from intric.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from intric.mcp_servers.application.mcp_server_settings_service import (
        MCPServerSettingsService,
    )
    from intric.prompt_library.application.prompt_library_service import (
        PromptLibraryService,
    )


class PersonalChatPolicyService:
    def __init__(
        self,
        user: UserInDB,
        repo: PersonalChatPolicyRepo,
        completion_model_crud_service: "CompletionModelCRUDService",
        mcp_server_settings_service: "MCPServerSettingsService",
        prompt_library_service: "PromptLibraryService",
    ) -> None:
        self.user = user
        self.repo = repo
        self.completion_model_crud_service = completion_model_crud_service
        self.mcp_server_settings_service = mcp_server_settings_service
        self.prompt_library_service = prompt_library_service

    async def get_policy(self) -> PersonalChatPolicy:
        """Get the tenant's policy, auto-creating an empty one if none exists.

        An auto-created empty policy has all `*_restriction_enabled=False`
        which means no user-facing change — safe to do lazily on first read.
        """
        validate_permission(self.user, Permission.ADMIN)
        existing = await self.repo.get_by_tenant(self.user.tenant_id)
        if existing is not None:
            return existing
        return await self.repo.create_empty(self.user.tenant_id)

    async def update_policy(
        self,
        *,
        models_restriction: tuple[bool, list[PolicyCompletionModel]] | None = None,
        mcp_restriction: tuple[bool, list[UUID]] | None = None,
        prompt_enforcement: tuple[bool, UUID | None] | None = None,
    ) -> PersonalChatPolicy:
        validate_permission(self.user, Permission.ADMIN)
        policy = await self.get_policy()

        if models_restriction is not None:
            enabled, models = models_restriction
            if enabled:
                await self._validate_models_belong_to_tenant(models)
            policy.set_models_restriction(enabled=enabled, models=models)

        if mcp_restriction is not None:
            enabled, ids = mcp_restriction
            if enabled and ids:
                await self._validate_mcp_servers_belong_to_tenant(ids)
            policy.set_mcp_restriction(enabled=enabled, ids=ids)

        if prompt_enforcement is not None:
            enabled, prompt_id = prompt_enforcement
            if enabled and prompt_id is not None:
                await self._validate_prompt_belongs_to_tenant(prompt_id)
            policy.set_prompt_enforcement(enabled=enabled, prompt_library_id=prompt_id)

        return await self.repo.save(policy, updated_by_user_id=self.user.id)

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

    async def _validate_mcp_servers_belong_to_tenant(self, ids: list[UUID]) -> None:
        tenant_servers = (
            await self.mcp_server_settings_service.get_available_mcp_servers()
        )
        enabled_ids = {s.id for s in tenant_servers if s.is_enabled}
        for sid in ids:
            if sid not in enabled_ids:
                raise BadRequestException(
                    f"MCP server {sid} is not enabled for this tenant"
                )

    async def _validate_prompt_belongs_to_tenant(self, prompt_id: UUID) -> None:
        # get_entry already enforces tenant-scope + admin-permission, and
        # raises NotFoundException for cross-tenant access (translates to 404).
        # We rebrand it here as a 400 because the issue is request-level, not
        # an unknown resource.
        try:
            await self.prompt_library_service.get_entry(prompt_id)
        except Exception:
            raise BadRequestException(
                f"Prompt library entry {prompt_id} not found in this tenant"
            )
