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

from eneo.flow_packages.domain.flow_package_manifest import EneoPackageKind
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageCompletionModelConstraints,
    FlowPackageKnowledgeGuidance,
    FlowPackageModelGuidance,
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageRequirementDataSensitivity,
    FlowPackageRequirementKind,
    FlowPackageResourceSlotRefJson,
    FlowPackageTemplateAssetGuidance,
    serialize_flow_package_slot_ref,
)
from eneo.flows.flow_resource_bindings import LocalResourceKind, ResourceSlotRef

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
    def serialize_slot_ref(
        self,
        slot_ref: ResourceSlotRef,
    ) -> FlowPackageResourceSlotRefJson:
        return serialize_flow_package_slot_ref(slot_ref)


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


class FlowPackageImportTargetState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    audio_transcription_required: bool = Field(
        description=(
            "Whether the portable package needs the target space's default "
            "transcription model."
        )
    )
    default_transcription_model_id: UUID | None = Field(
        description=(
            "Target-space transcription default captured by the plan, or null when "
            "unavailable or not applicable."
        )
    )

    @model_validator(mode="after")
    def validate_relevant_default(self) -> "FlowPackageImportTargetState":
        if (
            not self.audio_transcription_required
            and self.default_transcription_model_id is not None
        ):
            raise ValueError(
                "Non-audio package plans must not carry a transcription model."
            )
        return self

    @property
    def install_blocks(self) -> bool:
        return (
            self.audio_transcription_required
            and self.default_transcription_model_id is None
        )


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
    target_state: FlowPackageImportTargetState
    dependency_resolutions: list[FlowPackageDependencyResolutionEntry] = Field(
        default_factory=_empty_dependency_resolutions
    )

    @computed_field
    @property
    def can_install_as_draft(self) -> bool:
        return not self.target_state.install_blocks and all(
            not resolution.install_blocks for resolution in self.dependency_resolutions
        )

    @computed_field
    @property
    def can_publish_after_import(self) -> bool:
        return not self.target_state.install_blocks and all(
            not resolution.publish_blocks for resolution in self.dependency_resolutions
        )

    def storage_json(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            exclude={"can_install_as_draft", "can_publish_after_import"},
        )
