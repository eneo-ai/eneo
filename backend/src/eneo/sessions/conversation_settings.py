"""User choices for one conversation; assistant configuration still owns policy.

Explicit tool states distinguish a saved opt-in from a newly available tool
whose current default is off. They can only narrow the runtime's allowed set.
"""

from typing import Self, cast, get_args
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ModelWrapValidatorHandler,
    PrivateAttr,
    TypeAdapter,
    model_validator,
)

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.capabilities import (
    CapabilityAvailability,
    CapabilityPurpose,
)

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


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
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    settings: ConversationSettings
    _unknown_fields: dict[str, JsonValue] = PrivateAttr(default_factory=dict)
    _unknown_settings: dict[str, JsonValue] = PrivateAttr(default_factory=dict)
    _unknown_capabilities: dict[str, JsonValue] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def read_persisted_state(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        """Keep opaque stored choices out of the editable API contract.

        Only unknown fields are separated. Invalid values for known fields still
        fail validation; accepting a damaged known setting could weaken policy.
        """
        if not isinstance(value, dict):
            return handler(value)
        fields = cast(dict[str, object], value)
        if not isinstance(fields.get("settings"), dict):
            return handler(value)
        # Known fields may come from model_dump() with native UUID values and
        # UUID map keys. Their typed model owns validation; only opaque values
        # must already be JSON-safe so they can be preserved in storage.
        choices = cast(dict[str, object], fields["settings"])
        unknown = _JSON_OBJECT.validate_python(
            {
                k: v
                for k, v in choices.items()
                if k not in ConversationSettings.model_fields
            }
        )
        known = {k: v for k, v in choices.items() if k not in unknown}
        unknown_capabilities: dict[str, JsonValue] = {}
        capabilities = known.get("capability_states")
        if isinstance(capabilities, dict):
            capabilities = cast(dict[str, object], capabilities)
            purposes = get_args(CapabilityPurpose)
            unknown_capabilities = _JSON_OBJECT.validate_python(
                {k: v for k, v in capabilities.items() if k not in purposes}
            )
            known["capability_states"] = {
                k: v for k, v in capabilities.items() if k in purposes
            }
        state = handler({"revision": fields.get("revision"), "settings": known})
        state._unknown_settings = unknown
        state._unknown_capabilities = unknown_capabilities
        state._unknown_fields = _JSON_OBJECT.validate_python(
            {k: v for k, v in fields.items() if k not in cls.model_fields}
        )
        return state

    @property
    def is_compatible(self) -> bool:
        # Unknown capability names are dormant choices, never executable tools.
        # Unknown options may change safety semantics, so they block new work.
        return not self._unknown_settings and not self._unknown_fields

    def require_supported(self) -> None:
        if not self.is_compatible:
            raise BadRequestException(
                "This conversation contains settings unsupported by this app version. "
                "History is available, but settings changes and new runs are blocked."
            )

    def with_settings(self, settings: ConversationSettings) -> Self:
        self.require_supported()
        return self.model_copy(
            update={"revision": self.revision + 1, "settings": settings}
        )

    def to_storage(self) -> dict[str, JsonValue]:
        """Persist opaque choices too; public model_dump intentionally omits them."""
        choices = _JSON_OBJECT.validate_python(self.settings.model_dump(mode="json"))
        capabilities = _JSON_OBJECT.validate_python(choices["capability_states"])
        choices["capability_states"] = {**self._unknown_capabilities, **capabilities}
        return {
            **self._unknown_fields,
            "revision": self.revision,
            "settings": {**self._unknown_settings, **choices},
        }


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
    selected: bool
    reason: str | None = None


class ConversationCapability(CapabilityAvailability):
    selected: bool


class ConversationSettingsResolution(BaseModel):
    """Saved choices and current model/tool availability; never rewrites saved choices."""

    revision: int = Field(ge=0)
    settings: ConversationSettings
    settings_compatible: bool = True
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
    capabilities: list[ConversationCapability] = Field(
        default_factory=list[ConversationCapability]
    )
