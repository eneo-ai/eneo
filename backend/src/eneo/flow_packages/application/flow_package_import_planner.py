from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Final, TypeVar, assert_never
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flow_packages.application.flow_package_model_matching import (
    resolve_model_requirement,
)
from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_import_plan import (
    MAX_IMPORT_PLAN_SUGGESTIONS,
    FlowPackageDependencyResolutionEntry,
    FlowPackageImportPlan,
    FlowPackageImportPlanStatus,
    FlowPackageImportPlanSummary,
    FlowPackageImportTargetState,
    FlowPackageKnowledgeDependencyResolution,
    FlowPackageLocalCandidate,
    FlowPackageModelCandidate,
    FlowPackageTemplateAssetDependencyResolution,
)
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageKnowledgeRequirement,
    FlowPackageModelRequirement,
    FlowPackageRequirementEntry,
    FlowPackageRequirementKind,
    FlowPackageTemplateAssetRequirement,
)
from eneo.flows.application.flow_draft_materialization import (
    build_flow_draft_metadata_json,
)
from eneo.flows.domain.flow_step_validation import FlowGraphIssueCode
from eneo.flows.flow_authoring_spec import InputSource, InputType
from eneo.flows.flow_authoring_variable_rewriting import (
    flow_step_validation_views_from_draft_spec,
)
from eneo.flows.flow_resource_bindings import (
    ResourceSlotKind,
    local_resource_kinds_for_slot_kind,
)
from eneo.flows.flow_validators import (
    collect_step_graph_issues,
    validate_form_schema,
)
from eneo.flows.flow_validators_form import (
    validate_variable_alias_collisions_for_step_graph,
)
from eneo.main.exceptions import BadRequestException

CandidateT = TypeVar("CandidateT", bound=FlowPackageLocalCandidate)

_REQUIREMENT_SLOT_KIND: Final[dict[FlowPackageRequirementKind, ResourceSlotKind]] = {
    FlowPackageRequirementKind.MODEL: ResourceSlotKind.MODEL,
    FlowPackageRequirementKind.KNOWLEDGE: ResourceSlotKind.KNOWLEDGE,
    FlowPackageRequirementKind.TEMPLATE_ASSET: ResourceSlotKind.TEMPLATE_ASSET,
}


def _empty_candidates() -> list[FlowPackageLocalCandidate]:
    return []


def _empty_model_candidates() -> list[FlowPackageModelCandidate]:
    return []


class FlowPackageImportPlannerCandidates(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    models: list[FlowPackageModelCandidate] = Field(
        default_factory=_empty_model_candidates
    )
    knowledge: list[FlowPackageLocalCandidate] = Field(
        default_factory=_empty_candidates
    )
    template_assets: list[FlowPackageLocalCandidate] = Field(
        default_factory=_empty_candidates
    )

    @model_validator(mode="after")
    def validate_candidate_buckets(self) -> "FlowPackageImportPlannerCandidates":
        self.models = _validated_model_candidates(
            self.models,
        )
        self.knowledge = _validated_sorted_candidates(
            self.knowledge,
            ResourceSlotKind.KNOWLEDGE,
        )
        self.template_assets = _validated_sorted_candidates(
            self.template_assets,
            ResourceSlotKind.TEMPLATE_ASSET,
        )
        return self

    def for_non_model_slot_kind(
        self,
        slot_kind: ResourceSlotKind,
    ) -> tuple[FlowPackageLocalCandidate, ...]:
        match slot_kind:
            case ResourceSlotKind.KNOWLEDGE:
                return tuple(self.knowledge)
            case ResourceSlotKind.TEMPLATE_ASSET:
                return tuple(self.template_assets)
            case _:
                raise ValueError(
                    f"{slot_kind.value} is not a package import candidate bucket."
                )


def build_flow_package_import_plan(
    envelope: FlowPackageEnvelope,
    *,
    candidates: FlowPackageImportPlannerCandidates,
    default_transcription_model_id: UUID | None = None,
) -> FlowPackageImportPlan:
    envelope.validated_resource_contract()
    audio_transcription_required = _audio_transcription_required(envelope)
    effective_transcription_model_id = (
        default_transcription_model_id if audio_transcription_required else None
    )
    _validate_installable_draft(
        envelope,
        default_transcription_model_id=effective_transcription_model_id,
    )
    dependency_resolutions = [
        _resolve_requirement(requirement, candidates)
        for requirement in envelope.requirements.requirements
    ]
    return FlowPackageImportPlan(
        package_id=envelope.manifest.package_id,
        package_version=envelope.manifest.package_version,
        kind=envelope.manifest.kind,
        payload_schema=envelope.manifest.payload_schema,
        content_checksum=envelope.content_checksum,
        omissions=list(envelope.provenance.omissions),
        package_summary=_package_summary(envelope),
        target_state=FlowPackageImportTargetState(
            audio_transcription_required=audio_transcription_required,
            default_transcription_model_id=effective_transcription_model_id,
        ),
        dependency_resolutions=dependency_resolutions,
    )


def _validate_installable_draft(
    envelope: FlowPackageEnvelope,
    *,
    default_transcription_model_id: UUID | None,
) -> None:
    if not envelope.spec.steps:
        raise _invalid_flow_draft(
            "no_executable_steps",
            "Flow package draft must contain at least one step.",
        )
    steps = flow_step_validation_views_from_draft_spec(envelope.spec.steps)
    metadata_json = build_flow_draft_metadata_json(
        spec=envelope.spec,
        current_flow=None,
        default_transcription_model_id=default_transcription_model_id,
    )
    try:
        validate_form_schema(metadata_json)
        validate_variable_alias_collisions_for_step_graph(
            steps=steps,
            metadata_json=metadata_json,
        )
    except BadRequestException as exc:
        raise _invalid_flow_draft(exc.code, str(exc)) from exc

    issue = next(
        (
            candidate
            for candidate in collect_step_graph_issues(
                steps,
                metadata_json=metadata_json,
                require_complete_template_fill_config=True,
            )
            if candidate.code
            is not FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED
        ),
        None,
    )
    if issue is not None:
        raise _invalid_flow_draft(issue.code.value, issue.message)


def _audio_transcription_required(envelope: FlowPackageEnvelope) -> bool:
    return any(
        step.input_source is InputSource.FLOW_INPUT
        and step.input_type is InputType.AUDIO
        for step in envelope.spec.steps
    )


def _invalid_flow_draft(
    reason: str | None,
    message: str,
) -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.FLOW_DRAFT_INVALID,
        message=message or "Flow package draft is not installable.",
        context={"reason": reason or "invalid_flow_graph"},
    )


def _package_summary(envelope: FlowPackageEnvelope) -> FlowPackageImportPlanSummary:
    requirement_counts = Counter(
        requirement.kind for requirement in envelope.requirements.requirements
    )
    return FlowPackageImportPlanSummary(
        name=envelope.manifest.name,
        description=envelope.manifest.description,
        spec_hash=envelope.spec_hash,
        steps_count=len(envelope.spec.steps),
        requirements_count=len(envelope.requirements.requirements),
        requirements_by_kind=dict(requirement_counts),
    )


def _resolve_requirement(
    requirement: FlowPackageRequirementEntry,
    candidates: FlowPackageImportPlannerCandidates,
) -> FlowPackageDependencyResolutionEntry:
    match requirement:
        case FlowPackageModelRequirement():
            return resolve_model_requirement(
                requirement=requirement,
                candidates=tuple(candidates.models),
            )
        case FlowPackageKnowledgeRequirement():
            return _resolve_knowledge_requirement(requirement, candidates)
        case FlowPackageTemplateAssetRequirement():
            return _resolve_unsupported_template_requirement(requirement)
        case _:
            assert_never(requirement)


def _resolve_knowledge_requirement(
    requirement: FlowPackageKnowledgeRequirement,
    candidates: FlowPackageImportPlannerCandidates,
) -> FlowPackageKnowledgeDependencyResolution:
    slot_kind = _REQUIREMENT_SLOT_KIND[requirement.kind]
    matching_candidates = candidates.for_non_model_slot_kind(slot_kind)
    total_candidate_count = len(matching_candidates)
    suggestions = list(matching_candidates[:MAX_IMPORT_PLAN_SUGGESTIONS])
    status = _knowledge_resolution_status(
        required=requirement.required,
        total_candidate_count=total_candidate_count,
    )
    missing_required_candidate = requirement.required and total_candidate_count == 0

    return FlowPackageKnowledgeDependencyResolution(
        slot_ref=requirement.slot_ref,
        required=requirement.required,
        used_by_steps=list(requirement.used_by_steps),
        data_sensitivity=requirement.data_sensitivity,
        guidance=requirement.guidance,
        status=status,
        install_blocks=missing_required_candidate,
        publish_blocks=missing_required_candidate,
        selection_required_for_install=requirement.required,
        auto_select_allowed=False,
        suggestions=suggestions,
        total_candidate_count=total_candidate_count,
    )


def _resolve_unsupported_template_requirement(
    requirement: FlowPackageTemplateAssetRequirement,
) -> FlowPackageTemplateAssetDependencyResolution:
    return FlowPackageTemplateAssetDependencyResolution(
        slot_ref=requirement.slot_ref,
        required=requirement.required,
        used_by_steps=list(requirement.used_by_steps),
        data_sensitivity=requirement.data_sensitivity,
        guidance=requirement.guidance,
        status=FlowPackageImportPlanStatus.UNSUPPORTED,
        install_blocks=True,
        publish_blocks=True,
        selection_required_for_install=False,
        auto_select_allowed=False,
        suggestions=[],
        total_candidate_count=0,
    )


def _knowledge_resolution_status(
    *,
    required: bool,
    total_candidate_count: int,
) -> FlowPackageImportPlanStatus:
    if not required:
        return FlowPackageImportPlanStatus.SKIPPED_OPTIONAL
    if total_candidate_count == 0:
        return FlowPackageImportPlanStatus.UNRESOLVED_REQUIRED
    return FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION


def _validated_sorted_candidates(
    candidates: list[CandidateT],
    slot_kind: ResourceSlotKind,
) -> list[CandidateT]:
    _raise_invalid_candidates(candidates, slot_kind)
    return sorted(candidates, key=_candidate_sort_key)


def _validated_model_candidates(
    candidates: list[FlowPackageModelCandidate],
) -> list[FlowPackageModelCandidate]:
    _raise_invalid_candidates(candidates, ResourceSlotKind.MODEL)
    return list(candidates)


def _raise_invalid_candidates(
    candidates: Sequence[FlowPackageLocalCandidate],
    slot_kind: ResourceSlotKind,
) -> None:
    allowed_local_kinds = local_resource_kinds_for_slot_kind(slot_kind)
    invalid_candidates = [
        candidate
        for candidate in candidates
        if candidate.local_kind not in allowed_local_kinds
    ]
    if invalid_candidates:
        invalid_kind = invalid_candidates[0].local_kind.value
        raise ValueError(
            f"{invalid_kind} cannot satisfy {slot_kind.value} package candidates."
        )


def _candidate_sort_key(
    candidate: FlowPackageLocalCandidate,
) -> tuple[str, str, str]:
    return (
        candidate.label.casefold(),
        candidate.local_kind.value,
        str(candidate.local_id),
    )
