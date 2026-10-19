"""User choices for one conversation; assistant configuration still owns policy.

Explicit tool states distinguish a saved opt-in from a newly available tool
whose current default is off. They can only narrow the runtime's allowed set.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.mcp_servers.domain.capabilities import (
    CapabilityAvailability,
    CapabilityPurpose,
)


class ConversationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completion_model_id: UUID | None = None
    reasoning_effort: str | None = Field(default=None, max_length=32)
    mcp_server_states: dict[UUID, bool] = Field(
        default_factory=dict[UUID, bool], max_length=512
    )
    capability_states: dict[CapabilityPurpose, bool] = Field(
        default_factory=dict[CapabilityPurpose, bool]
    )
    require_tool_approval: bool = False

    def disabled_servers(self, defaults: list[UUID]) -> list[UUID]:
        return list(
            {id for id in defaults if id not in self.mcp_server_states}
            | {id for id, enabled in self.mcp_server_states.items() if not enabled}
        )

    def disabled_capabilities(
        self, defaults: list[CapabilityPurpose]
    ) -> list[CapabilityPurpose]:
        disabled: set[CapabilityPurpose] = {
            purpose for purpose in defaults if purpose not in self.capability_states
        }
        disabled.update(
            purpose
            for purpose, enabled in self.capability_states.items()
            if not enabled
        )
        return list(disabled)


class ConversationSettingsState(BaseModel):
    revision: int = Field(ge=1)
    settings: ConversationSettings


class ConversationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    settings: ConversationSettings


class ConversationMcpServer(BaseModel):
    """A general tool offered by current policy, including why it cannot run."""

    id: UUID
    name: str
    description: str | None = None
    icon_url: str | None = None
    available: bool
    reason: str | None = None


class ConversationSettingsResolution(BaseModel):
    """Saved choices and current model/tool availability; never rewrites saved choices."""

    revision: int = Field(ge=0)
    settings: ConversationSettings
    # None for assistants/group chats whose model is not user-selectable.
    available_models: list[CompletionModelPublic] | None = None
    effective_model: CompletionModelPublic | None = None
    model_unavailable: bool = False
    model_locked: bool = False
    supports_tool_calling: bool = False
    effective_reasoning_effort: str | None = None
    default_reasoning_effort: str | None = None
    reasoning_effort_options: list[str] = Field(default_factory=list[str])
    mcp_servers: list[ConversationMcpServer] = Field(
        default_factory=list[ConversationMcpServer]
    )
    capabilities: list[CapabilityAvailability] = Field(
        default_factory=list[CapabilityAvailability]
    )
    default_disabled_mcp_server_ids: list[UUID] = Field(default_factory=list[UUID])
    default_disabled_capabilities: list[CapabilityPurpose] = Field(
        default_factory=list[CapabilityPurpose]
    )
