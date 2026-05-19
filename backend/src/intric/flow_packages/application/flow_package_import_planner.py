from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Final, TypeVar, assert_never

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intric.flow_packages.application.flow_package_model_matching import (
    resolve_model_requirement,
)
from intric.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from intric.flow_packages.domain.flow_package_import_plan import (
    MAX_IMPORT_PLAN_SUGGESTIONS,
    FlowPackageDependencyResolutionEntry,
    FlowPackageImportPlan,
    FlowPackageImportPlanStatus,
    FlowPackageImportPlanSummary,
    FlowPackageKnowledgeDependencyResolution,
    FlowPackageLocalCandidate,
    FlowPackageMcpToolDependencyResolution,
    FlowPackageModelCandidate,
    FlowPackageTemplateAssetDependencyResolution,
)
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageKnowledgeRequirement,
    FlowPackageMcpToolRequirement,
    FlowPackageModelRequirement,
    FlowPackageRequirementEntry,
    FlowPackageRequirementKind,
    FlowPackageTemplateAssetRequirement,
)
from intric.flows.flow_resource_bindings import (
    ResourceSlotKind,
    local_resource_kinds_for_slot_kind,
)

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
) -> FlowPackageImportPlan:
    dependency_resolutions = [
        _resolve_requirement(requirement, candidates)
        for requirement in envelope.requirements.requirements
    ]
    return FlowPackageImportPlan(
        package_id=envelope.manifest.package_id,
        package_version=envelope.manifest.package_version,
        package_kind=envelope.manifest.package_kind,
        payload_schema=envelope.manifest.payload_schema,
        content_checksum=envelope.content_checksum,
        package_summary=_package_summary(envelope),
        dependency_resolutions=dependency_resolutions,
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
        case FlowPackageMcpToolRequirement():
            return _resolve_mcp_setup_requirement(requirement)
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

    return FlowPackageKnowledgeDependencyResolution(
        slot_ref=requirement.slot_ref,
        required=requirement.required,
        used_by_steps=list(requirement.used_by_steps),
        data_sensitivity=requirement.data_sensitivity,
        guidance=requirement.guidance,
        status=status,
        install_blocks=False,
        publish_blocks=False,
        selection_required_for_install=False,
        auto_select_allowed=False,
        suggestions=suggestions,
        total_candidate_count=total_candidate_count,
    )


def _resolve_mcp_setup_requirement(
    requirement: FlowPackageMcpToolRequirement,
) -> FlowPackageMcpToolDependencyResolution:
    return FlowPackageMcpToolDependencyResolution(
        slot_ref=requirement.slot_ref,
        required=requirement.required,
        used_by_steps=list(requirement.used_by_steps),
        data_sensitivity=requirement.data_sensitivity,
        guidance=requirement.guidance,
        server_slot_ref=requirement.server_slot_ref,
        status=FlowPackageImportPlanStatus.UNSUPPORTED,
        install_blocks=True,
        publish_blocks=True,
        selection_required_for_install=False,
        auto_select_allowed=False,
        suggestions=[],
        total_candidate_count=0,
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
        return FlowPackageImportPlanStatus.MANUAL_SETUP_REQUIRED
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
