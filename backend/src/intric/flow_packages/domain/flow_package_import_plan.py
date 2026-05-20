from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Generic, Literal, TypeAlias, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

from intric.flow_packages.domain.flow_package_manifest import EneoPackageKind
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageCompletionModelConstraints,
    FlowPackageKnowledgeGuidance,
    FlowPackageMcpToolGuidance,
    FlowPackageModelGuidance,
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageRequirementDataSensitivity,
    FlowPackageRequirementKind,
    FlowPackageTemplateAssetGuidance,
)
from intric.flows.flow_resource_bindings import LocalResourceKind, ResourceSlotRef

MAX_IMPORT_PLAN_SUGGESTIONS: Final[int] = 10


class FlowPackageImportPlanStatus(StrEnum):
    RESOLVED_EXACT = "resolved_exact"
    REQUIRES_HUMAN_CONFIRMATION = "requires_human_confirmation"
    MANUAL_SETUP_REQUIRED = "manual_setup_required"
    UNRESOLVED_REQUIRED = "unresolved_required"
    SKIPPED_OPTIONAL = "skipped_optional"
    # Unsupported dependencies stay visible in validation/import plans so users know why import is blocked.
    UNSUPPORTED = "unsupported"


class FlowPackagePolicyStatus(StrEnum):
    ALLOWED = "allowed"
    WARNING = "warning"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class FlowPackageModelMatchIssue(StrEnum):
    MODEL_CONTEXT_TOO_SMALL = "model_context_too_small"
    MODEL_IDENTITY_NOT_PREFERRED = "model_identity_not_preferred"
    MODEL_KIND_MISMATCH = "model_kind_mismatch"
    MODEL_REASONING_REQUIRED = "model_reasoning_required"
    MODEL_TOOL_CALLING_REQUIRED = "model_tool_calling_required"
    MODEL_VISION_REQUIRED = "model_vision_required"


class FlowPackageLocalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    local_kind: LocalResourceKind
    local_id: UUID
    label: str

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Local candidate label must not be empty.")
        return normalized


class FlowPackageModelCandidate(FlowPackageLocalCandidate):
    model_kind: FlowPackageModelKind
    identity: FlowPackageModelIdentity
    security_level: int | None = Field(default=None, ge=0)
    max_context_tokens: int | None = Field(default=None, ge=1)
    supports_vision: bool = False
    supports_reasoning: bool = False
    supports_tool_calling: bool = False

    @model_validator(mode="after")
    def validate_local_kind(self) -> "FlowPackageModelCandidate":
        expected_local_kind = _local_kind_for_model_kind(self.model_kind)
        if self.local_kind is not expected_local_kind:
            raise ValueError(
                f"{self.model_kind.value} package model candidates must use "
                f"{expected_local_kind.value} local resources."
            )
        return self


class FlowPackageRejectedModelCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate: FlowPackageModelCandidate
    reasons: list[FlowPackageModelMatchIssue]

    @field_validator("reasons")
    @classmethod
    def normalize_reasons(
        cls,
        value: list[FlowPackageModelMatchIssue],
    ) -> list[FlowPackageModelMatchIssue]:
        normalized = _sorted_unique_match_issues(value)
        if not normalized:
            raise ValueError("Rejected model candidates must include a reason.")
        return normalized


SuggestionCandidateT = TypeVar("SuggestionCandidateT", bound=FlowPackageLocalCandidate)


def _empty_model_match_issues() -> list[FlowPackageModelMatchIssue]:
    return []


def _empty_rejected_model_candidates() -> list[FlowPackageRejectedModelCandidate]:
    return []


class FlowPackageDependencyResolutionBase(
    BaseModel,
    Generic[SuggestionCandidateT],
):
    model_config = ConfigDict(extra="forbid", strict=True)

    slot_ref: ResourceSlotRef
    required: bool
    used_by_steps: list[str] = Field(default_factory=list)
    data_sensitivity: FlowPackageRequirementDataSensitivity | None = None
    status: FlowPackageImportPlanStatus
    install_blocks: bool
    publish_blocks: bool
    selection_required_for_install: bool
    auto_select_allowed: bool
    suggestions: list[SuggestionCandidateT]
    total_candidate_count: int = Field(ge=0)

    @field_serializer("slot_ref")
    def serialize_slot_ref(self, slot_ref: ResourceSlotRef) -> dict[str, str]:
        return _serialize_slot_ref(slot_ref)


class FlowPackageModelDependencyResolution(
    FlowPackageDependencyResolutionBase[FlowPackageModelCandidate]
):
    kind: Literal[FlowPackageRequirementKind.MODEL] = FlowPackageRequirementKind.MODEL
    guidance: FlowPackageModelGuidance | None = None
    model_kind: FlowPackageModelKind
    matching_preferences: FlowPackageModelMatchingPreferences
    completion_constraints: FlowPackageCompletionModelConstraints | None = None
    eligible_candidate_count: int = Field(ge=0)
    policy_status: FlowPackagePolicyStatus
    selection_warnings: list[FlowPackageModelMatchIssue] = Field(
        default_factory=_empty_model_match_issues
    )
    rejected_candidates: list[FlowPackageRejectedModelCandidate] = Field(
        default_factory=_empty_rejected_model_candidates
    )

    @field_validator("selection_warnings")
    @classmethod
    def normalize_selection_warnings(
        cls,
        value: list[FlowPackageModelMatchIssue],
    ) -> list[FlowPackageModelMatchIssue]:
        return _sorted_unique_match_issues(value)

    @model_validator(mode="after")
    def validate_candidate_counts(self) -> "FlowPackageModelDependencyResolution":
        if self.eligible_candidate_count > self.total_candidate_count:
            raise ValueError(
                "Eligible model candidate count cannot exceed total candidate count."
            )
        if self.auto_select_allowed and (
            self.status is not FlowPackageImportPlanStatus.RESOLVED_EXACT
            or self.policy_status is not FlowPackagePolicyStatus.ALLOWED
            or self.install_blocks
            or self.publish_blocks
            or self.selection_warnings
        ):
            raise ValueError(
                "Model auto-selection requires an exact, policy-allowed match with no blockers or warnings."
            )
        return self


class FlowPackageKnowledgeDependencyResolution(
    FlowPackageDependencyResolutionBase[FlowPackageLocalCandidate]
):
    kind: Literal[FlowPackageRequirementKind.KNOWLEDGE] = (
        FlowPackageRequirementKind.KNOWLEDGE
    )
    guidance: FlowPackageKnowledgeGuidance | None = None


class FlowPackageMcpToolDependencyResolution(
    FlowPackageDependencyResolutionBase[FlowPackageLocalCandidate]
):
    kind: Literal[FlowPackageRequirementKind.MCP_TOOL] = (
        FlowPackageRequirementKind.MCP_TOOL
    )
    guidance: FlowPackageMcpToolGuidance | None = None
    server_slot_ref: ResourceSlotRef | None = None

    @field_serializer("server_slot_ref")
    def serialize_server_slot_ref(
        self,
        slot_ref: ResourceSlotRef | None,
    ) -> dict[str, str] | None:
        if slot_ref is None:
            return None
        return _serialize_slot_ref(slot_ref)


class FlowPackageTemplateAssetDependencyResolution(
    FlowPackageDependencyResolutionBase[FlowPackageLocalCandidate]
):
    kind: Literal[FlowPackageRequirementKind.TEMPLATE_ASSET] = (
        FlowPackageRequirementKind.TEMPLATE_ASSET
    )
    guidance: FlowPackageTemplateAssetGuidance | None = None


FlowPackageDependencyResolutionEntry: TypeAlias = Annotated[
    FlowPackageModelDependencyResolution
    | FlowPackageKnowledgeDependencyResolution
    | FlowPackageMcpToolDependencyResolution
    | FlowPackageTemplateAssetDependencyResolution,
    Field(discriminator="kind"),
]


def _empty_dependency_resolutions() -> list[FlowPackageDependencyResolutionEntry]:
    return []


class FlowPackageImportPlanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    description: str
    spec_hash: str
    steps_count: int = Field(ge=0)
    requirements_count: int = Field(ge=0)
    requirements_by_kind: dict[FlowPackageRequirementKind, int]


def _serialize_slot_ref(slot_ref: ResourceSlotRef) -> dict[str, str]:
    return {
        "kind": slot_ref.kind.value,
        "label": slot_ref.label,
        "slot": slot_ref.slot,
    }


def _local_kind_for_model_kind(model_kind: FlowPackageModelKind) -> LocalResourceKind:
    match model_kind:
        case FlowPackageModelKind.COMPLETION_MODEL:
            return LocalResourceKind.COMPLETION_MODEL
        case FlowPackageModelKind.TRANSCRIPTION_MODEL:
            return LocalResourceKind.TRANSCRIPTION_MODEL


def _sorted_unique_match_issues(
    issues: list[FlowPackageModelMatchIssue],
) -> list[FlowPackageModelMatchIssue]:
    return sorted(set(issues), key=lambda issue: issue.value)


class FlowPackageImportPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    package_id: str
    package_version: str
    package_kind: EneoPackageKind
    payload_schema: str
    content_checksum: str
    package_summary: FlowPackageImportPlanSummary
    dependency_resolutions: list[FlowPackageDependencyResolutionEntry] = Field(
        default_factory=_empty_dependency_resolutions
    )

    @computed_field
    @property
    def can_install_as_draft(self) -> bool:
        return all(
            not resolution.install_blocks for resolution in self.dependency_resolutions
        )

    @computed_field
    @property
    def can_publish_after_import(self) -> bool:
        return all(
            not resolution.publish_blocks for resolution in self.dependency_resolutions
        )
