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
class PersonalChatPolicy:
    """Tenant-level governance config for the personal chat assistant.

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
    mcp_server_ids: list[UUID] = field(default_factory=lambda: [])  # noqa: C408
    default_prompt_library_id: UUID | None = None

    updated_at: datetime | None = None
    updated_by_user_id: UUID | None = None

    def set_models_restriction(
        self,
        *,
        enabled: bool,
        models: list[PolicyCompletionModel],
    ) -> None:
        if enabled and not models:
            raise BadRequestException(
                "Cannot enable model restriction without any allowed models"
            )
        ids_seen: set[UUID] = set()
        for m in models:
            if m.completion_model_id in ids_seen:
                raise BadRequestException("Duplicate completion model in policy")
            ids_seen.add(m.completion_model_id)
        if sum(1 for m in models if m.is_default) > 1:
            raise BadRequestException("Only one completion model can be default")
        self.models_restriction_enabled = enabled
        self.completion_models = list(models) if enabled else []

    def set_mcp_restriction(self, *, enabled: bool, ids: list[UUID]) -> None:
        if len(ids) != len(set(ids)):
            raise BadRequestException("Duplicate MCP server IDs")
        # enabled=True with empty list is allowed: "no MCP servers in
        # personal chat" (explicit deny-all).
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
