# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


import asyncio
from typing import TYPE_CHECKING

from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    resolve,
)

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant
    from eneo.completion_models.application.completion_model_crud_service import (
        CompletionModelCRUDService,
    )
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.governance_policy.domain.governance_policy_repo import (
        GovernancePolicyRepo,
    )
    from eneo.mcp_servers.application.mcp_server_settings_service import (
        MCPServerSettingsService,
    )
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.prompt_library.domain.prompt_library_repo import PromptLibraryRepo
    from eneo.users.user import UserInDB


class EffectiveConfigService:
    """Composes the inputs to the pure resolver from live repos/services.

    Lives in `application/` because it does I/O. The resolver itself stays
    pure (no awaits, no DB) — this service is the translator between live
    state and the resolver's contract.
    """

    def __init__(
        self,
        user: "UserInDB",
        policy_repo: "GovernancePolicyRepo",
        prompt_library_repo: "PromptLibraryRepo",
        completion_model_crud_service: "CompletionModelCRUDService",
        mcp_server_settings_service: "MCPServerSettingsService",
    ) -> None:
        self.user = user
        self.policy_repo = policy_repo
        self.prompt_library_repo = prompt_library_repo
        self.completion_model_crud_service = completion_model_crud_service
        self.mcp_server_settings_service = mcp_server_settings_service

    async def resolve_for(
        self, assistant: "Assistant", *, space_is_personal: bool
    ) -> EffectiveConfig:
        """Compute the effective config for an assistant.

        Returns the empty config for non-default assistants, non-personal
        spaces, and when no policy exists — all via the resolver's own
        short-circuits.
        """
        if not assistant.is_default or not space_is_personal:
            return resolve(
                assistant=assistant,
                space_is_personal=space_is_personal,
                policy=None,
                tenant_completion_models=[],
                tenant_mcp_servers=[],
                library_prompt_text=None,
            )

        # A personal default assistant maps to exactly one scope today. When
        # finer scopes are added, derive it from (assistant, space) here.
        policy = await self.policy_repo.get_by_tenant(
            self.user.tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
        )
        if policy is None:
            return resolve(
                assistant=assistant,
                space_is_personal=space_is_personal,
                policy=None,
                tenant_completion_models=[],
                tenant_mcp_servers=[],
                library_prompt_text=None,
            )

        # Fetch only the catalogs the resolver will actually consult: it reads
        # tenant_completion_models only when models_restriction_enabled and
        # tenant_mcp_servers only when mcp_restriction_enabled. An all-disabled
        # policy row exists for any tenant whose admin merely opened the config
        # page, so skipping these keeps the chat hot path off two full-table
        # scans per resolution. The independent fetches run concurrently.
        async def _load_models() -> "list[CompletionModel]":
            if not policy.models_restriction_enabled:
                return []
            # Tenant-accessible completion models. Global models (tenant_id=NULL)
            # show up here because `can_access` already accounts for them.
            return await self.completion_model_crud_service.get_available_completion_models()

        async def _load_mcp_servers() -> "list[MCPServer]":
            if not policy.mcp_restriction_enabled:
                return []
            servers = await self.mcp_server_settings_service.get_available_mcp_servers()
            return [server for server in servers if server.is_enabled]

        async def _load_prompt_text() -> str | None:
            if policy.default_prompt_library_id is None:
                return None
            entry = await self.prompt_library_repo.get(
                id=policy.default_prompt_library_id,
                tenant_id=self.user.tenant_id,
            )
            return entry.text if entry is not None else None

        tenant_models, tenant_mcp_servers, library_prompt_text = await asyncio.gather(
            _load_models(), _load_mcp_servers(), _load_prompt_text()
        )

        return resolve(
            assistant=assistant,
            space_is_personal=space_is_personal,
            policy=policy,
            tenant_completion_models=tenant_models,
            tenant_mcp_servers=tenant_mcp_servers,
            library_prompt_text=library_prompt_text,
        )
