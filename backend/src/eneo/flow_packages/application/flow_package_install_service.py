from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from eneo.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
)
from eneo.flow_packages.application.flow_package_model_matching import (
    hard_model_candidate_rejection_reasons,
)
from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_import_plan import (
    FlowPackageImportPlan,
    FlowPackageImportTargetState,
    FlowPackageLocalCandidate,
    FlowPackageModelCandidate,
)
from eneo.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportSelection,
)
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageModelRequirement,
    FlowPackageTemplateAssetRequirement,
)
from eneo.flows.application.flow_authoring_command import (
    CreateFlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, StepSpec
from eneo.flows.flow_resource_bindings import (
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


@dataclass(frozen=True, slots=True)
class ResolvedFlowPackageInstallCommand:
    envelope: FlowPackageEnvelope
    import_plan: FlowPackageImportPlan
    install_spec: FlowDraftSpecCore
    selection: FlowPackageImportSelection

    @property
    def default_transcription_model_id(self) -> UUID | None:
        return self.import_plan.target_state.default_transcription_model_id


def resolve_flow_package_install_command(
    *,
    envelope: FlowPackageEnvelope,
    import_plan: FlowPackageImportPlan,
    expected_content_checksum: str,
    expected_target_state: FlowPackageImportTargetState,
    selection: FlowPackageImportSelection,
    candidates: FlowPackageImportPlannerCandidates,
) -> ResolvedFlowPackageInstallCommand:
    if (
        expected_content_checksum != envelope.content_checksum
        or import_plan.content_checksum != envelope.content_checksum
    ):
        raise FlowPackageValidationError(
            code=FlowPackageErrorCode.CHECKSUM_MISMATCH,
            message="Flow package does not match the reviewed import plan.",
            context={
                "expected_content_checksum": expected_content_checksum,
                "current_content_checksum": envelope.content_checksum,
            },
        )
    if expected_target_state != import_plan.target_state:
        raise _target_state_changed(
            expected=expected_target_state,
            current=import_plan.target_state,
        )
    if import_plan.target_state.install_blocks:
        raise FlowPackageValidationError(
            code=FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE,
            message=("The target space has no transcription model for this package."),
            context={
                "slot_ref": "model.flow_input_transcription",
                "local_kind": LocalResourceKind.TRANSCRIPTION_MODEL.value,
                "local_id": "unselected",
            },
        )

    validated_selection = validate_flow_package_install_selection(
        envelope=envelope,
        selected_bindings=selection.bindings_tuple(),
        candidates=candidates,
    )
    install_spec = _spec_with_unbound_knowledge_refs_removed(
        spec=envelope.spec,
        selected_slot_refs=validated_selection.selected_slot_refs,
    )
    return ResolvedFlowPackageInstallCommand(
        envelope=envelope,
        import_plan=import_plan,
        install_spec=install_spec,
        selection=FlowPackageImportSelection(
            selected_bindings=list(validated_selection.resource_bindings)
        ),
    )


def _target_state_changed(
    *,
    expected: FlowPackageImportTargetState,
    current: FlowPackageImportTargetState,
) -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE,
        message=("The target space transcription model changed after import planning."),
        context={
            "slot_ref": "model.flow_input_transcription",
            "local_kind": LocalResourceKind.TRANSCRIPTION_MODEL.value,
            "local_id": str(expected.default_transcription_model_id or "unselected"),
            "current_local_id": str(
                current.default_transcription_model_id or "unselected"
            ),
        },
    )


class FlowPackageInstallService:
    def __init__(
        self,
        authoring_service: FlowAuthoringCommandService | None = None,
    ) -> None:
        self._authoring_service = authoring_service or FlowAuthoringCommandService()

    async def install_as_draft(
        self,
        *,
        command: ResolvedFlowPackageInstallCommand,
        flow_service: FlowService,
        space_id: UUID,
    ) -> FlowPackageInstallResult:
        envelope = command.envelope
        authoring_command = CreateFlowAuthoringCommand(
            space_id=space_id,
            spec=command.install_spec,
            origin=FlowPackageAuthoringOrigin(
                package_id=envelope.manifest.package_id,
                package_version=envelope.manifest.package_version,
                content_checksum=envelope.content_checksum,
            ),
            resource_bindings=command.selection.bindings_tuple(),
            default_transcription_model_id=command.default_transcription_model_id,
        )
        materialized = await self._authoring_service.apply(
            command=authoring_command,
            flow_service=flow_service,
        )
        return FlowPackageInstallResult(
            flow_id=materialized.flow_id,
            flow_name=materialized.flow_name,
            package_id=envelope.manifest.package_id,
            package_version=envelope.manifest.package_version,
            content_checksum=envelope.content_checksum,
            steps_created=materialized.steps_created,
            resource_bindings_count=len(command.selection.selected_bindings),
        )


def validate_flow_package_install_selection(
    *,
    envelope: FlowPackageEnvelope,
    selected_bindings: tuple[LocalResourceBinding, ...],
    candidates: FlowPackageImportPlannerCandidates,
) -> ValidatedFlowPackageInstallSelection:
    selected_bindings_by_ref = index_local_resource_bindings(selected_bindings)
    selected_slot_refs = frozenset(selected_bindings_by_ref)
    resource_contract = envelope.validated_resource_contract()
    declared_slot_refs = resource_contract.declared_slot_refs
    referenced_slot_refs = resource_contract.referenced_slot_refs

    _reject_template_asset_requirements(envelope)
    _reject_unknown_selected_bindings(
        selected_slot_refs=selected_slot_refs,
        declared_slot_refs=declared_slot_refs,
    )
    canonical_bindings = tuple(
        LocalResourceBinding(
            slot_ref=declared_slot_refs[slot_ref],
            local_kind=binding.local_kind,
            local_id=binding.local_id,
        )
        for slot_ref, binding in sorted(selected_bindings_by_ref.items())
    )
    _reject_unavailable_local_resources(
        selected_bindings=canonical_bindings,
        candidates=candidates,
    )
    _reject_ineligible_selected_models(
        envelope=envelope,
        selected_bindings=canonical_bindings,
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
        resource_bindings=canonical_bindings,
        required_slot_refs=frozenset(required_slot_refs),
        selected_slot_refs=selected_slot_refs,
    )


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
