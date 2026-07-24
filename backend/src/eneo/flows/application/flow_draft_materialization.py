from __future__ import annotations

import enum
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from eneo.flows.enums import FlowInputSource, FlowInputType, FlowOutputMode
from eneo.flows.flow_authoring_runtime_input import resolve_runtime_input_config
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    OutputType,
    StepSpec,
    metadata_json_from_authoring_form_fields,
)
from eneo.flows.flow_authoring_transcription import (
    apply_audio_transcription_defaults,
)
from eneo.flows.flow_authoring_variable_rewriting import (
    build_ref_to_order,
    rewrite_step_spec_variables,
)
from eneo.flows.flow_metadata import normalize_persisted_flow_metadata
from eneo.flows.flow_review_policy import FlowStepReviewPolicy
from eneo.flows.http_transport import redact_persisted_config
from eneo.flows.step_lineage import existing_step_ref_for_order
from eneo.main.exceptions import BadRequestException


class FlowDraftStepChangeKind(str, enum.Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


def _default_assistants_to_create() -> list[FlowDraftAssistantToCreate]:
    return []


def _default_assistants_to_update() -> list[FlowDraftAssistantToUpdate]:
    return []


def _default_assistants_to_delete() -> list[FlowDraftAssistantToDelete]:
    return []


def _default_compiled_steps() -> list[FlowDraftCompiledStep]:
    return []


class FlowDraftAssistantToCreate(BaseModel):
    plan_step_ref: str
    assistant_spec: AssistantSpec


class FlowDraftAssistantToUpdate(BaseModel):
    existing_step_ref: str | None = None
    existing_step_id: UUID | None = None
    existing_assistant_id: UUID | None = None
    assistant_spec: AssistantSpec


class FlowDraftAssistantToDelete(BaseModel):
    existing_step_ref: str | None = None
    step_id: UUID | None = None
    assistant_id: UUID | None = None


class FlowDraftCompiledStep(BaseModel):
    plan_step_ref: str
    change_kind: FlowDraftStepChangeKind
    step_order: int
    user_description: str
    input_source: FlowInputSource
    input_type: FlowInputType
    output_mode: FlowOutputMode
    output_type: OutputType
    assistant_id: UUID | None = None
    existing_step_ref: str | None = None
    input_bindings: FlowPersistedJsonObject | None = None
    input_contract: FlowPersistedJsonObject | None = None
    output_contract: FlowPersistedJsonObject | None = None
    input_config: FlowPersistedJsonObject | None = None
    output_config: FlowPersistedJsonObject | None = None
    review_policy: FlowStepReviewPolicy | None = None


class FlowDraftChangeSet(BaseModel):
    flow_name: str
    flow_description: str
    assistants_to_create: list[FlowDraftAssistantToCreate] = Field(
        default_factory=_default_assistants_to_create
    )
    assistants_to_update: list[FlowDraftAssistantToUpdate] = Field(
        default_factory=_default_assistants_to_update
    )
    assistants_to_delete: list[FlowDraftAssistantToDelete] = Field(
        default_factory=_default_assistants_to_delete
    )
    compiled_steps: list[FlowDraftCompiledStep] = Field(
        default_factory=_default_compiled_steps
    )
    metadata_json: FlowPersistedJsonObject | None = None


class FlowDraftMaterializationStage(str, enum.Enum):
    FLOW_CREATED = "flow_created"
    ASSISTANTS_CREATED = "assistants_created"
    ASSISTANTS_CONFIGURED = "assistants_configured"
    ASSISTANTS_UPDATED = "assistants_updated"
    FLOW_UPDATED = "flow_updated"
    ASSISTANTS_DELETED = "assistants_deleted"


@dataclass(frozen=True, slots=True)
class FlowDraftMaterializationProgress:
    stage: FlowDraftMaterializationStage
    assistants_created: int = 0
    assistants_configured: int = 0
    assistants_updated: int = 0
    assistants_deleted: int = 0
    flow_created: bool = False
    flow_updated: bool = False


@dataclass(frozen=True, slots=True)
class FlowDraftMaterializationResult:
    flow_id: UUID
    flow_name: str
    draft_revision: int
    steps_created: int
    steps_updated: int
    steps_removed: int


def compile_flow_draft_changeset(
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    *,
    removed_existing_step_refs: frozenset[str] = frozenset(),
    default_transcription_model_id: UUID | None = None,
) -> FlowDraftChangeSet:
    existing_by_ref: dict[str, FlowStep] = {}
    if current_flow:
        for step in current_flow.steps:
            existing_by_ref[existing_step_ref_for_order(step.step_order)] = step
    _validate_existing_step_ref_coverage(
        spec=spec,
        existing_by_ref=existing_by_ref,
        removed_existing_step_refs=removed_existing_step_refs,
    )

    ref_to_order = build_ref_to_order(spec.steps)
    assistants_to_create: list[FlowDraftAssistantToCreate] = []
    assistants_to_update: list[FlowDraftAssistantToUpdate] = []
    compiled_steps: list[FlowDraftCompiledStep] = []

    for index, step_spec in enumerate(spec.steps):
        step_order = index + 1
        existing_step = _resolve_existing_step(step_spec, existing_by_ref)
        rewritten_spec = rewrite_step_spec_variables(step_spec, ref_to_order)

        if existing_step is not None:
            assistants_to_update.append(
                FlowDraftAssistantToUpdate(
                    existing_step_id=existing_step.id,
                    existing_assistant_id=existing_step.assistant_id,
                    assistant_spec=rewritten_spec.assistant_spec,
                )
            )
            compiled_steps.append(
                _compile_modified_step(
                    step_spec=rewritten_spec,
                    existing_step=existing_step,
                    step_order=step_order,
                )
            )
            continue

        assistants_to_create.append(
            FlowDraftAssistantToCreate(
                plan_step_ref=step_spec.plan_step_ref,
                assistant_spec=rewritten_spec.assistant_spec,
            )
        )
        compiled_steps.append(
            _compile_new_step(
                step_spec=rewritten_spec,
                step_order=step_order,
            )
        )

    assistants_to_delete: list[FlowDraftAssistantToDelete] = []
    if current_flow:
        for ref in sorted(removed_existing_step_refs):
            existing_step = existing_by_ref[ref]
            assistants_to_delete.append(
                FlowDraftAssistantToDelete(
                    step_id=existing_step.id,
                    assistant_id=existing_step.assistant_id,
                )
            )

    return FlowDraftChangeSet(
        flow_name=spec.flow_name,
        flow_description=spec.flow_description,
        assistants_to_create=assistants_to_create,
        assistants_to_update=assistants_to_update,
        assistants_to_delete=assistants_to_delete,
        compiled_steps=compiled_steps,
        metadata_json=build_flow_draft_metadata_json(
            spec=spec,
            current_flow=current_flow,
            default_transcription_model_id=default_transcription_model_id,
        ),
    )


def _validate_existing_step_ref_coverage(
    *,
    spec: FlowDraftSpecCore,
    existing_by_ref: dict[str, FlowStep],
    removed_existing_step_refs: frozenset[str],
) -> None:
    preserved_refs = [
        step.existing_step_ref
        for step in spec.steps
        if step.existing_step_ref is not None
    ]
    validate_existing_step_ref_coverage(
        current_refs=set(existing_by_ref),
        preserved_refs=preserved_refs,
        removed_existing_step_refs=removed_existing_step_refs,
    )


def validate_existing_step_ref_coverage(
    *,
    current_refs: set[str],
    preserved_refs: list[str],
    removed_existing_step_refs: frozenset[str],
) -> None:
    if not current_refs:
        if removed_existing_step_refs:
            raise _invalid_existing_step_ref(
                "Create flow commands cannot remove existing steps.",
                reason="create_cannot_remove_existing_step_refs",
                removed_refs=sorted(removed_existing_step_refs),
            )
        if preserved_refs:
            raise _invalid_existing_step_ref(
                "Create flow commands cannot reference existing steps.",
                reason="create_cannot_use_existing_step_ref",
                existing_step_ref=preserved_refs[0],
            )
        return

    preserved_ref_set = set(preserved_refs)
    duplicate_refs = sorted(
        ref for ref in preserved_ref_set if preserved_refs.count(ref) > 1
    )
    if duplicate_refs:
        raise _invalid_existing_step_ref(
            "Each existing step can be preserved or updated at most once.",
            reason="duplicate_existing_step_ref",
            duplicate_refs=duplicate_refs,
        )

    unknown_preserved_refs = sorted(preserved_ref_set - current_refs)
    if unknown_preserved_refs:
        raise _invalid_existing_step_ref(
            f"Spec references unknown existing steps: {unknown_preserved_refs}.",
            reason="unknown_existing_step_ref",
            unknown_refs=unknown_preserved_refs,
            valid_refs=sorted(current_refs),
        )

    unknown_removed_refs = sorted(removed_existing_step_refs - current_refs)
    if unknown_removed_refs:
        raise _invalid_existing_step_ref(
            "Removal list references unknown existing steps.",
            reason="unknown_removed_existing_step_ref",
            unknown_refs=unknown_removed_refs,
        )

    overlap_refs = sorted(preserved_ref_set & removed_existing_step_refs)
    if overlap_refs:
        raise _invalid_existing_step_ref(
            "An existing step cannot be both preserved and removed.",
            reason="preserved_and_removed_existing_step_ref",
            overlap_refs=overlap_refs,
        )

    missing_refs = sorted(current_refs - preserved_ref_set - removed_existing_step_refs)
    if missing_refs:
        raise _invalid_existing_step_ref(
            "Every existing step must be preserved or explicitly removed.",
            reason="missing_existing_step_ref",
            missing_refs=missing_refs,
        )


def preserve_modified_step_output_config(
    *,
    step_spec: StepSpec,
    existing_step: FlowStep,
) -> StepSpec:
    if step_spec.output_config is not None:
        return step_spec
    if step_spec.output_mode.value != existing_step.output_mode:
        return step_spec
    if step_spec.output_type.value != existing_step.output_type:
        return step_spec
    return step_spec.model_copy(
        update={"output_config": redact_persisted_config(existing_step.output_config)}
    )


def build_flow_draft_metadata_json(
    *,
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    default_transcription_model_id: UUID | None = None,
) -> FlowPersistedJsonObject | None:
    metadata: FlowPersistedJsonObject = {}
    if current_flow and current_flow.metadata_json:
        metadata = normalize_persisted_flow_metadata(current_flow.metadata_json) or {}

    form_metadata = metadata_json_from_authoring_form_fields(spec.form_fields)
    if form_metadata is not None:
        metadata.update(form_metadata)

    metadata = (
        apply_audio_transcription_defaults(
            metadata=metadata if metadata else None,
            spec=spec,
            default_transcription_model_id=default_transcription_model_id,
        )
        or {}
    )
    return metadata if metadata else None


def _resolve_existing_step(
    step_spec: StepSpec,
    existing_by_ref: dict[str, FlowStep],
) -> FlowStep | None:
    if step_spec.existing_step_ref is None:
        return None
    resolved = existing_by_ref.get(step_spec.existing_step_ref)
    if resolved is None:
        valid_refs = sorted(existing_by_ref.keys())
        raise BadRequestException(
            (
                f"existing_step_ref '{step_spec.existing_step_ref}' does not match "
                f"any existing step. Valid refs: {valid_refs}"
            ),
            code="invalid_existing_step_ref",
            context={
                "existing_step_ref": step_spec.existing_step_ref,
                "valid_refs": valid_refs,
            },
        )
    return resolved


def _invalid_existing_step_ref(
    message: str,
    *,
    reason: str,
    **context: object,
) -> BadRequestException:
    return BadRequestException(
        message,
        code="invalid_existing_step_ref",
        context={"reason": reason, **context},
    )


def _compile_new_step(
    *,
    step_spec: StepSpec,
    step_order: int,
) -> FlowDraftCompiledStep:
    return FlowDraftCompiledStep(
        plan_step_ref=step_spec.plan_step_ref,
        change_kind=FlowDraftStepChangeKind.ADDED,
        step_order=step_order,
        user_description=step_spec.name,
        assistant_id=None,
        input_source=FlowInputSource(step_spec.input_source.value),
        input_type=FlowInputType(step_spec.input_type.value),
        output_mode=FlowOutputMode(step_spec.output_mode.value),
        output_type=OutputType(step_spec.output_type.value),
        input_bindings=step_spec.input_bindings,
        input_contract=step_spec.input_contract,
        output_contract=step_spec.output_contract,
        input_config=resolve_runtime_input_config(step_spec=step_spec),
        output_config=step_spec.output_config,
        review_policy=step_spec.review_policy,
    )


def _compile_modified_step(
    *,
    step_spec: StepSpec,
    existing_step: FlowStep,
    step_order: int,
) -> FlowDraftCompiledStep:
    effective_spec = preserve_modified_step_output_config(
        step_spec=step_spec,
        existing_step=existing_step,
    )
    return FlowDraftCompiledStep(
        plan_step_ref=effective_spec.plan_step_ref,
        change_kind=FlowDraftStepChangeKind.MODIFIED,
        step_order=step_order,
        user_description=effective_spec.name,
        assistant_id=existing_step.assistant_id,
        input_source=FlowInputSource(effective_spec.input_source.value),
        input_type=FlowInputType(effective_spec.input_type.value),
        output_mode=FlowOutputMode(effective_spec.output_mode.value),
        output_type=OutputType(effective_spec.output_type.value),
        input_bindings=effective_spec.input_bindings,
        input_contract=effective_spec.input_contract,
        output_contract=effective_spec.output_contract,
        input_config=resolve_runtime_input_config(
            step_spec=effective_spec,
            existing_input_config=redact_persisted_config(existing_step.input_config),
        ),
        output_config=effective_spec.output_config,
        review_policy=effective_spec.review_policy,
    )
