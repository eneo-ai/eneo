# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import TYPE_CHECKING

from intric.personal_chat_policy.domain.policy_resolver import (
    EffectiveConfig,
    resolve,
)

if TYPE_CHECKING:
    from intric.assistants.assistant import Assistant
    from intric.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from intric.mcp_servers.application.mcp_server_settings_service import (
        MCPServerSettingsService,
    )
    from intric.personal_chat_policy.domain.personal_chat_policy_repo import (
        PersonalChatPolicyRepo,
    )
    from intric.prompt_library.domain.prompt_library_repo import PromptLibraryRepo
    from intric.users.user import UserInDB


class EffectiveConfigService:
    """Composes the inputs to the pure resolver from live repos/services.

    Lives in `application/` because it does I/O. The resolver itself stays
    pure (no awaits, no DB) — this service is the translator between live
    state and the resolver's contract.
    """

    def __init__(
        self,
        user: "UserInDB",
        policy_repo: "PersonalChatPolicyRepo",
        prompt_library_repo: "PromptLibraryRepo",
        completion_model_crud_service: "CompletionModelCRUDService",
        mcp_server_settings_service: "MCPServerSettingsService",
    ) -> None:
        self.user = user
        self.policy_repo = policy_repo
        self.prompt_library_repo = prompt_library_repo
        self.completion_model_crud_service = completion_model_crud_service
        self.mcp_server_settings_service = mcp_server_settings_service

    async def resolve_for(self, assistant: "Assistant") -> EffectiveConfig:
        """Compute the effective config for an assistant.

        Returns the empty config for non-default assistants and when no
        policy exists — both via the resolver's own short-circuits.
        """
        if not assistant.is_default:
            return resolve(
                assistant=assistant,
                policy=None,
                tenant_completion_models=[],
                tenant_mcp_servers=[],
                library_prompt_text=None,
            )

        policy = await self.policy_repo.get_by_tenant(self.user.tenant_id)
        if policy is None:
            return resolve(
                assistant=assistant,
                policy=None,
                tenant_completion_models=[],
                tenant_mcp_servers=[],
                library_prompt_text=None,
            )

        # Tenant-accessible completion models. Global models (tenant_id=NULL)
        # show up here naturally because `can_access` already accounts for them.
        tenant_models = (
            await self.completion_model_crud_service.get_available_completion_models()
        )

        # All tenant MCP servers (enabled and disabled — the resolver
        # filters down to the policy whitelist).
        tenant_mcp_servers = (
            await self.mcp_server_settings_service.get_available_mcp_servers()
        )

        library_prompt_text: str | None = None
        if policy.default_prompt_library_id is not None:
            entry = await self.prompt_library_repo.get(
                id=policy.default_prompt_library_id,
                tenant_id=self.user.tenant_id,
            )
            if entry is not None:
                library_prompt_text = entry.text

        return resolve(
            assistant=assistant,
            policy=policy,
            tenant_completion_models=tenant_models,
            tenant_mcp_servers=tenant_mcp_servers,
            library_prompt_text=library_prompt_text,
        )
