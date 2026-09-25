"""User choices for one conversation; assistant configuration still owns policy.

Explicit tool states distinguish a saved opt-in from a newly available tool
whose current default is off. They can only narrow the runtime's allowed set.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.mcp_servers.domain.capabilities import CapabilityPurpose


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
