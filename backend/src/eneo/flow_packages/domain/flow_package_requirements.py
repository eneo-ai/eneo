from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from eneo.flow_packages.domain.flow_package_checksum import json_object_from_model
from eneo.flows.flow_resource_bindings import ResourceSlotKind, ResourceSlotRef
from eneo.json_types import JsonObject


class FlowPackageRequirementKind(StrEnum):
    MODEL = "model"
    KNOWLEDGE = "knowledge"
    MCP_TOOL = "mcp_tool"
    TEMPLATE_ASSET = "template_asset"


class FlowPackageModelKind(StrEnum):
    COMPLETION_MODEL = "completion_model"
    TRANSCRIPTION_MODEL = "transcription_model"


MAX_MODEL_MATCHING_IDENTITIES: Final[int] = 50


def _empty_string_list() -> list[str]:
    return []


def _empty_model_identities() -> list["FlowPackageModelIdentity"]:
    return []


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_text_list(value: list[str]) -> list[str]:
    return [item.strip() for item in value if item.strip()]


class FlowPackageRequirementDataSensitivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    handles_personal_data: bool = False
    handles_sensitive_case_data: bool = False
    publisher_classification_label: str | None = None
    publisher_classification_description: str | None = None
    notes: str | None = None

    @field_validator(
        "publisher_classification_label",
        "publisher_classification_description",
        "notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class FlowPackageModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str
    model: str

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("Model identity provider must not be empty.")
        return normalized

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        # Provider model identifiers can be case-sensitive; only trim whitespace.
        normalized = value.strip()
        if not normalized:
            raise ValueError("Model identity model must not be empty.")
        return normalized


class FlowPackageModelMatchingPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tested_with: list[FlowPackageModelIdentity] = Field(
        default_factory=_empty_model_identities,
        max_length=MAX_MODEL_MATCHING_IDENTITIES,
    )
    publisher_suggested: list[FlowPackageModelIdentity] = Field(
        default_factory=_empty_model_identities,
        max_length=MAX_MODEL_MATCHING_IDENTITIES,
    )


class FlowPackageCompletionModelConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    minimum_context_tokens: int | None = Field(default=None, ge=1)
    requires_vision: bool = False
    requires_reasoning: bool = False
    requires_tool_calling: bool = False


class FlowPackageModelGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str | None = None
    quality_notes: str | None = None
    minimum_expected_quality: str | None = None

    @field_validator("summary", "quality_notes", "minimum_expected_quality")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class FlowPackageKnowledgeGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str | None = None
    recommended_sources: list[str] = Field(default_factory=_empty_string_list)
    do_not_include: list[str] = Field(default_factory=_empty_string_list)
    setup_notes: str | None = None

    @field_validator("summary", "setup_notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("recommended_sources", "do_not_include")
    @classmethod
    def normalize_text_entries(cls, value: list[str]) -> list[str]:
        return _normalize_text_list(value)


class FlowPackageMcpToolGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str | None = None
    expected_behavior: str | None = None
    auth_notes: str | None = None
    risk_notes: str | None = None

    @field_validator("summary", "expected_behavior", "auth_notes", "risk_notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class FlowPackageTemplateAssetGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str | None = None
    replacement_notes: str | None = None
    placeholder_notes: str | None = None

    @field_validator("summary", "replacement_notes", "placeholder_notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class FlowPackageRequirementBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    slot_ref: ResourceSlotRef
    required: bool = True
    used_by_steps: list[str] = Field(default_factory=list)
    data_sensitivity: FlowPackageRequirementDataSensitivity | None = None

    @field_serializer("slot_ref")
    def serialize_slot_ref(self, slot_ref: ResourceSlotRef) -> dict[str, str]:
        return _serialize_slot_ref(slot_ref)

    @field_validator("used_by_steps")
    @classmethod
    def normalize_used_by_steps(cls, value: list[str]) -> list[str]:
        return _normalize_text_list(value)


class FlowPackageModelRequirement(FlowPackageRequirementBase):
    kind: Literal[FlowPackageRequirementKind.MODEL] = FlowPackageRequirementKind.MODEL
    guidance: FlowPackageModelGuidance | None = None
    model_kind: FlowPackageModelKind = FlowPackageModelKind.COMPLETION_MODEL
    matching_preferences: FlowPackageModelMatchingPreferences = Field(
        default_factory=FlowPackageModelMatchingPreferences
    )
    completion_constraints: FlowPackageCompletionModelConstraints | None = None

    @model_validator(mode="after")
    def validate_model_slot(self) -> "FlowPackageModelRequirement":
        _require_slot_kind(self.slot_ref, ResourceSlotKind.MODEL)
        if (
            self.model_kind is FlowPackageModelKind.TRANSCRIPTION_MODEL
            and self.completion_constraints is not None
        ):
            raise ValueError(
                "Transcription model requirements cannot carry completion constraints."
            )
        return self


class FlowPackageKnowledgeRequirement(FlowPackageRequirementBase):
    """Tenant-local knowledge used by the publisher, imported as setup guidance in V1.

    `required=True` means the publisher considered the knowledge important for
    equivalent results, not that the V1 importer must bind it before draft creation.
    """

    kind: Literal[FlowPackageRequirementKind.KNOWLEDGE] = (
        FlowPackageRequirementKind.KNOWLEDGE
    )
    guidance: FlowPackageKnowledgeGuidance | None = None

    @model_validator(mode="after")
    def validate_knowledge_slot(self) -> "FlowPackageKnowledgeRequirement":
        _require_slot_kind(self.slot_ref, ResourceSlotKind.KNOWLEDGE)
        return self


class FlowPackageMcpToolRequirement(FlowPackageRequirementBase):
    kind: Literal[FlowPackageRequirementKind.MCP_TOOL] = (
        FlowPackageRequirementKind.MCP_TOOL
    )
    guidance: FlowPackageMcpToolGuidance | None = None
    server_slot_ref: ResourceSlotRef | None = None

    @field_serializer("server_slot_ref")
    def serialize_server_slot_ref(
        self, slot_ref: ResourceSlotRef | None
    ) -> dict[str, str] | None:
        if slot_ref is None:
            return None
        return _serialize_slot_ref(slot_ref)

    @model_validator(mode="after")
    def validate_mcp_tool_slots(self) -> "FlowPackageMcpToolRequirement":
        _require_slot_kind(self.slot_ref, ResourceSlotKind.MCP_TOOL)
        if self.server_slot_ref is not None:
            _require_slot_kind(self.server_slot_ref, ResourceSlotKind.MCP_SERVER)
        return self


class FlowPackageTemplateAssetRequirement(FlowPackageRequirementBase):
    kind: Literal[FlowPackageRequirementKind.TEMPLATE_ASSET] = (
        FlowPackageRequirementKind.TEMPLATE_ASSET
    )
    guidance: FlowPackageTemplateAssetGuidance | None = None

    @model_validator(mode="after")
    def validate_template_asset_slot(self) -> "FlowPackageTemplateAssetRequirement":
        _require_slot_kind(self.slot_ref, ResourceSlotKind.TEMPLATE_ASSET)
        return self


FlowPackageRequirementEntry: TypeAlias = Annotated[
    FlowPackageModelRequirement
    | FlowPackageKnowledgeRequirement
    | FlowPackageMcpToolRequirement
    | FlowPackageTemplateAssetRequirement,
    Field(discriminator="kind"),
]


def _default_requirements() -> list[FlowPackageRequirementEntry]:
    return []


class FlowPackageRequirementSet(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    requirements: list[FlowPackageRequirementEntry] = Field(
        default_factory=_default_requirements
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported schema version.")
        return value

    @model_validator(mode="after")
    def validate_unique_slots(self) -> "FlowPackageRequirementSet":
        seen_refs: set[str] = set()
        for requirement in self.requirements:
            slot_ref = requirement.slot_ref.ref
            if slot_ref in seen_refs:
                raise ValueError(f"Duplicate package requirement slot '{slot_ref}'.")
            seen_refs.add(slot_ref)
        return self

    def canonical_hash_input(self) -> JsonObject:
        return json_object_from_model(self)


def _require_slot_kind(slot_ref: ResourceSlotRef, expected: ResourceSlotKind) -> None:
    if slot_ref.kind is not expected:
        raise ValueError(
            f"Requirement slot '{slot_ref.ref}' must be a {expected.value} slot."
        )


def _serialize_slot_ref(slot_ref: ResourceSlotRef) -> dict[str, str]:
    return {
        "kind": slot_ref.kind.value,
        "label": slot_ref.label,
        "slot": slot_ref.slot,
    }
