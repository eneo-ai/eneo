# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PolicyCompletionModelInput(BaseModel):
    completion_model_id: UUID
    is_default: bool = False


class ModelsRestrictionInput(BaseModel):
    enabled: bool
    models: list[PolicyCompletionModelInput] = []
    # Whitelisted ModelProvider IDs. Effective allowed-model set is the
    # UNION of `models` and "all org-enabled models under any provider in
    # `provider_ids`" — a provider whitelist subscribes to that provider's
    # future models, not a snapshot.
    provider_ids: list[UUID] = []


class McpRestrictionInput(BaseModel):
    enabled: bool
    server_ids: list[UUID] = []


class PromptEnforcementInput(BaseModel):
    enabled: bool
    prompt_library_id: UUID | None = None


class GovernancePolicyUpdate(BaseModel):
    models_restriction: ModelsRestrictionInput | None = None
    mcp_restriction: McpRestrictionInput | None = None
    prompt_enforcement: PromptEnforcementInput | None = None


# Output models — minimal references. The full completion-model /
# MCP-server / prompt objects can be fetched separately from their
# existing admin endpoints.


class PolicyCompletionModelPublic(BaseModel):
    completion_model_id: UUID
    is_default: bool


class ModelsRestrictionPublic(BaseModel):
    enabled: bool
    models: list[PolicyCompletionModelPublic]
    provider_ids: list[UUID]


class McpRestrictionPublic(BaseModel):
    enabled: bool
    server_ids: list[UUID]


class PromptEnforcementPublic(BaseModel):
    enabled: bool
    prompt_library_id: UUID | None


class GovernancePolicyPublic(BaseModel):
    models_restriction: ModelsRestrictionPublic
    mcp_restriction: McpRestrictionPublic
    prompt_enforcement: PromptEnforcementPublic
    updated_at: datetime | None
    updated_by_user_id: UUID | None
