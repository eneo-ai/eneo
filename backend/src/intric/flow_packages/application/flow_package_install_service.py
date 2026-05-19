from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from intric.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
)
from intric.flow_packages.application.flow_package_model_matching import (
    hard_model_candidate_rejection_reasons,
)
from intric.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from intric.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from intric.flow_packages.domain.flow_package_import_plan import (
    FlowPackageLocalCandidate,
    FlowPackageModelCandidate,
)
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageMcpToolRequirement,
    FlowPackageModelRequirement,
    FlowPackageTemplateAssetRequirement,
)
from intric.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from intric.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
)
from intric.flows.application.flow_service import FlowService
from intric.flows.flow_authoring_spec import AssistantSpec, FlowDraftSpecCore, StepSpec
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
    index_local_resource_bindings,
)


@dataclass(frozen=True, slots=True)
class ValidatedFlowPackageInstallSelection:
    resource_bindings: tuple[LocalResourceBinding, ...]
    required_slot_refs: frozenset[str]
    selected_slot_refs: frozenset[str]


@dataclass(frozen=True, slots=True)
class FlowPackageInstallResult:
    flow_id: UUID
    flow_name: str
    package_id: str
    package_version: str
    content_checksum: str
    steps_created: int
    resource_bindings_count: int


class FlowPackageInstallService:
    def __init__(self, materializer: FlowDraftMaterializer | None = None) -> None:
        self._materializer = materializer or FlowDraftMaterializer()

    async def install_as_draft(
        self,
        *,
        envelope: FlowPackageEnvelope,
        flow_service: FlowService,
        space_id: UUID,
        selected_bindings: tuple[LocalResourceBinding, ...],
        candidates: FlowPackageImportPlannerCandidates,
        default_transcription_model_id: UUID | None = None,
    ) -> FlowPackageInstallResult:
        selection = validate_flow_package_install_selection(
            envelope=envelope,
            selected_bindings=selected_bindings,
            candidates=candidates,
        )
        install_spec = _spec_with_unbound_knowledge_refs_removed(
            spec=envelope.spec,
            selected_slot_refs=selection.selected_slot_refs,
        )
        changeset = compile_flow_draft_changeset(
            install_spec,
            current_flow=None,
            default_transcription_model_id=default_transcription_model_id,
        )
        materialized = await self._materializer.execute(
            changeset=changeset,
            flow_service=flow_service,
            space_id=space_id,
            flow_id=None,
            resource_bindings=selection.resource_bindings,
            binding_source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )
        return FlowPackageInstallResult(
            flow_id=materialized.flow_id,
            flow_name=materialized.flow_name,
            package_id=envelope.manifest.package_id,
            package_version=envelope.manifest.package_version,
            content_checksum=envelope.content_checksum,
            steps_created=materialized.steps_created,
            resource_bindings_count=len(selection.resource_bindings),
        )


def validate_flow_package_install_selection(
    *,
    envelope: FlowPackageEnvelope,
    selected_bindings: tuple[LocalResourceBinding, ...],
    candidates: FlowPackageImportPlannerCandidates,
) -> ValidatedFlowPackageInstallSelection:
    selected_bindings_by_ref = index_local_resource_bindings(selected_bindings)
    selected_slot_refs = frozenset(selected_bindings_by_ref)
    declared_slot_refs = _declared_slot_refs(envelope)
    referenced_slot_refs = _referenced_slot_refs(envelope.spec)

    _reject_template_asset_requirements(envelope)
    _reject_mcp_setup_requirements(envelope)
    _reject_unknown_referenced_slots(
        referenced_slot_refs=referenced_slot_refs,
        declared_slot_refs=declared_slot_refs,
    )
    _reject_unknown_selected_bindings(
        selected_slot_refs=selected_slot_refs,
        declared_slot_refs=declared_slot_refs,
    )
    _reject_unavailable_local_resources(
        selected_bindings=selected_bindings,
        candidates=candidates,
    )
    _reject_ineligible_selected_models(
        envelope=envelope,
        selected_bindings=selected_bindings,
        candidates=candidates,
    )

    required_slot_refs = _install_required_slot_refs(
        envelope=envelope,
        referenced_slot_refs=referenced_slot_refs,
        declared_slot_refs=declared_slot_refs,
    )
    _reject_missing_required_bindings(
        required_slot_refs=required_slot_refs,
        selected_slot_refs=selected_slot_refs,
    )

    return ValidatedFlowPackageInstallSelection(
        resource_bindings=selected_bindings,
        required_slot_refs=frozenset(required_slot_refs),
        selected_slot_refs=selected_slot_refs,
    )


def _declared_slot_refs(envelope: FlowPackageEnvelope) -> dict[str, ResourceSlotRef]:
    declared: dict[str, ResourceSlotRef] = {}
    for requirement in envelope.requirements.requirements:
        declared.setdefault(requirement.slot_ref.ref, requirement.slot_ref)
        if (
            isinstance(requirement, FlowPackageMcpToolRequirement)
            and requirement.server_slot_ref is not None
        ):
            declared.setdefault(
                requirement.server_slot_ref.ref,
                requirement.server_slot_ref,
            )
    return declared


def _referenced_slot_refs(spec: FlowDraftSpecCore) -> frozenset[str]:
    refs: set[str] = set()
    for step in spec.steps:
        refs.update(_assistant_slot_refs(step.assistant_spec))
    return frozenset(refs)


def _assistant_slot_refs(assistant: AssistantSpec) -> tuple[str, ...]:
    refs: list[str] = []
    if assistant.model_ref is not None:
        refs.append(assistant.model_ref)
    refs.extend(assistant.knowledge_refs)
    refs.extend(assistant.mcp_server_refs)
    refs.extend(assistant.mcp_tool_refs)
    return tuple(refs)


def _spec_with_unbound_knowledge_refs_removed(
    *,
    spec: FlowDraftSpecCore,
    selected_slot_refs: frozenset[str],
) -> FlowDraftSpecCore:
    """Remove setup-only knowledge slots that the importer did not bind locally."""

    updated_steps: list[StepSpec] = []
    changed = False
    for step in spec.steps:
        selected_knowledge_refs = [
            ref
            for ref in step.assistant_spec.knowledge_refs
            if ref in selected_slot_refs
        ]
        if selected_knowledge_refs == step.assistant_spec.knowledge_refs:
            updated_steps.append(step)
            continue

        changed = True
        updated_steps.append(
            step.model_copy(
                update={
                    "assistant_spec": step.assistant_spec.model_copy(
                        update={"knowledge_refs": selected_knowledge_refs}
                    )
                }
            )
        )

    if not changed:
        return spec
    return spec.model_copy(update={"steps": updated_steps})


def _reject_mcp_setup_requirements(envelope: FlowPackageEnvelope) -> None:
    requirement_refs = sorted(
        requirement.slot_ref.ref
        for requirement in envelope.requirements.requirements
        if isinstance(requirement, FlowPackageMcpToolRequirement)
    )
    spec_refs = sorted(
        ref
        for step in envelope.spec.steps
        for ref in (
            tuple(step.assistant_spec.mcp_server_refs)
            + tuple(step.assistant_spec.mcp_tool_refs)
        )
    )
    mcp_refs = requirement_refs + [
        ref for ref in spec_refs if ref not in requirement_refs
    ]
    if not mcp_refs:
        return
    raise FlowPackageValidationError(
        code=FlowPackageErrorCode.IMPORT_MCP_MANUAL_SETUP_REQUIRED,
        message=(
            "Flow package import does not install or map MCP resources in this version; "
            "remove MCP resource slots from the package and document the required manual setup."
        ),
        context={"slot_ref": mcp_refs[0], "ref_count": len(mcp_refs)},
    )


def _reject_template_asset_requirements(envelope: FlowPackageEnvelope) -> None:
    for requirement in envelope.requirements.requirements:
        if isinstance(requirement, FlowPackageTemplateAssetRequirement):
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.IMPORT_TEMPLATE_ASSETS_UNSUPPORTED,
                message="Flow package import does not support template asset installation yet.",
                context={"slot_ref": requirement.slot_ref.ref},
            )


def _reject_ineligible_selected_models(
    *,
    envelope: FlowPackageEnvelope,
    selected_bindings: tuple[LocalResourceBinding, ...],
    candidates: FlowPackageImportPlannerCandidates,
) -> None:
    requirements_by_ref = {
        requirement.slot_ref.ref: requirement
        for requirement in envelope.requirements.requirements
        if isinstance(requirement, FlowPackageModelRequirement)
    }
    candidates_by_target = {
        (candidate.local_kind, candidate.local_id): candidate
        for candidate in candidates.models
    }
    for binding in selected_bindings:
        requirement = requirements_by_ref.get(binding.slot_ref.ref)
        if requirement is None:
            continue
        candidate = candidates_by_target.get((binding.local_kind, binding.local_id))
        if candidate is None:
            continue
        rejection_reasons = hard_model_candidate_rejection_reasons(
            requirement=requirement,
            candidate=candidate,
        )
        if not rejection_reasons:
            continue
        raise FlowPackageValidationError(
            code=FlowPackageErrorCode.IMPORT_SELECTED_MODEL_INELIGIBLE,
            message="Selected model does not satisfy the package slot's hard requirements.",
            context={
                "slot_ref": binding.slot_ref.ref,
                "local_kind": binding.local_kind.value,
                "local_id": str(binding.local_id),
                "reason": rejection_reasons[0].value,
                "reason_count": len(rejection_reasons),
            },
        )


def _reject_unknown_referenced_slots(
    *,
    referenced_slot_refs: frozenset[str],
    declared_slot_refs: dict[str, ResourceSlotRef],
) -> None:
    unknown_refs = sorted(referenced_slot_refs - declared_slot_refs.keys())
    if not unknown_refs:
        return
    raise FlowPackageValidationError(
        code=FlowPackageErrorCode.IMPORT_DRAFT_REFERENCES_UNDECLARED_SLOT,
        message="Flow package draft references a resource slot that is not declared.",
        context={"slot_ref": unknown_refs[0], "unknown_count": len(unknown_refs)},
    )


def _reject_unknown_selected_bindings(
    *,
    selected_slot_refs: frozenset[str],
    declared_slot_refs: dict[str, ResourceSlotRef],
) -> None:
    unknown_refs = sorted(selected_slot_refs - declared_slot_refs.keys())
    if not unknown_refs:
        return
    raise FlowPackageValidationError(
        code=FlowPackageErrorCode.IMPORT_UNKNOWN_RESOURCE_BINDING,
        message="Flow package import selected an undeclared resource slot.",
        context={"slot_ref": unknown_refs[0], "unknown_count": len(unknown_refs)},
    )


def _reject_unavailable_local_resources(
    *,
    selected_bindings: tuple[LocalResourceBinding, ...],
    candidates: FlowPackageImportPlannerCandidates,
) -> None:
    available_targets = _available_candidate_targets(candidates)
    for binding in selected_bindings:
        target = (binding.local_kind, binding.local_id)
        if target in available_targets:
            continue
        raise FlowPackageValidationError(
            code=FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE,
            message="Flow package import selected a resource that is not available in the target space.",
            context={
                "slot_ref": binding.slot_ref.ref,
                "local_kind": binding.local_kind.value,
                "local_id": str(binding.local_id),
            },
        )


def _available_candidate_targets(
    candidates: FlowPackageImportPlannerCandidates,
) -> frozenset[tuple[LocalResourceKind, UUID]]:
    return frozenset(
        (candidate.local_kind, candidate.local_id)
        for candidate in _iter_candidates(candidates)
    )


def _iter_candidates(
    candidates: FlowPackageImportPlannerCandidates,
) -> Iterable[FlowPackageLocalCandidate | FlowPackageModelCandidate]:
    yield from candidates.models
    yield from candidates.knowledge
    yield from candidates.template_assets


def _install_required_slot_refs(
    *,
    envelope: FlowPackageEnvelope,
    referenced_slot_refs: frozenset[str],
    declared_slot_refs: dict[str, ResourceSlotRef],
) -> frozenset[str]:
    required_model_requirements = {
        requirement.slot_ref.ref
        for requirement in envelope.requirements.requirements
        if isinstance(requirement, FlowPackageModelRequirement) and requirement.required
    }
    # The install validator rejects undeclared refs before this helper, so every
    # referenced slot can be classified by its declared portable slot kind here.
    referenced_model_slots = {
        ref
        for ref in referenced_slot_refs
        if declared_slot_refs[ref].kind is ResourceSlotKind.MODEL
    }
    return frozenset(required_model_requirements | referenced_model_slots)


def _reject_missing_required_bindings(
    *,
    required_slot_refs: frozenset[str],
    selected_slot_refs: frozenset[str],
) -> None:
    missing_refs = sorted(required_slot_refs - selected_slot_refs)
    if not missing_refs:
        return
    raise FlowPackageValidationError(
        code=FlowPackageErrorCode.IMPORT_MISSING_REQUIRED_RESOURCE_BINDING,
        message="Flow package import is missing a required resource binding.",
        context={"slot_ref": missing_refs[0], "missing_count": len(missing_refs)},
    )
