# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from intric.main.exceptions import BadRequestException


@dataclass
class PolicyCompletionModel:
    completion_model_id: UUID
    is_default: bool = False


@dataclass
class PersonalAssistantPolicy:
    """Tenant-level governance config for the personal assistant.

    All `*_restriction_enabled` flags default to False — an auto-created
    empty policy yields no user-facing change.
    """

    id: UUID | None
    tenant_id: UUID

    models_restriction_enabled: bool = False
    mcp_restriction_enabled: bool = False
    prompt_enforcement_enabled: bool = False

    completion_models: list[PolicyCompletionModel] = field(
        default_factory=lambda: []  # noqa: C408
    )
    # Whitelisted ModelProvider IDs. Effective allowed-model set is the
    # UNION of `completion_models` and "all org-enabled models under any
    # provider in `model_provider_ids`" — so a provider whitelist is a
    # subscription to that provider's future models, not a snapshot.
    model_provider_ids: list[UUID] = field(default_factory=lambda: [])  # noqa: C408
    mcp_server_ids: list[UUID] = field(default_factory=lambda: [])  # noqa: C408
    default_prompt_library_id: UUID | None = None

    updated_at: datetime | None = None
    updated_by_user_id: UUID | None = None

    def set_models_restriction(
        self,
        *,
        enabled: bool,
        models: list[PolicyCompletionModel],
        provider_ids: list[UUID] | None = None,
    ) -> None:
        provider_ids = list(provider_ids or [])
        if enabled and not models and not provider_ids:
            raise BadRequestException(
                "Cannot enable model restriction without any allowed providers "
                "or models"
            )
        ids_seen: set[UUID] = set()
        for m in models:
            if m.completion_model_id in ids_seen:
                raise BadRequestException("Duplicate completion model in policy")
            ids_seen.add(m.completion_model_id)
        if sum(1 for m in models if m.is_default) > 1:
            raise BadRequestException("Only one completion model can be default")
        if len(set(provider_ids)) != len(provider_ids):
            raise BadRequestException("Duplicate model provider in policy")
        self.models_restriction_enabled = enabled
        self.completion_models = list(models) if enabled else []
        self.model_provider_ids = list(provider_ids) if enabled else []

    def set_mcp_restriction(self, *, enabled: bool, ids: list[UUID]) -> None:
        if len(ids) != len(set(ids)):
            raise BadRequestException("Duplicate MCP server IDs")
        # enabled=True with empty list is allowed: "no MCP servers in
        # personal assistant" (explicit deny-all).
        self.mcp_restriction_enabled = enabled
        self.mcp_server_ids = list(ids) if enabled else []

    def set_prompt_enforcement(
        self, *, enabled: bool, prompt_library_id: UUID | None
    ) -> None:
        if enabled and prompt_library_id is None:
            raise BadRequestException(
                "Cannot enable prompt enforcement without selecting a prompt"
            )
        self.prompt_enforcement_enabled = enabled
        self.default_prompt_library_id = prompt_library_id if enabled else None
