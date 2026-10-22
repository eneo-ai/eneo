"""Compile an authoring spec into the steps and assistants of a new draft
flow. A flow package installs as a new draft through this changeset."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.flows.application.flow_authoring_refusal import (
    FlowAuthoringRefusalCode,
    FlowAuthoringRefusalException,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.enums import FlowInputSource, FlowInputType, FlowOutputMode
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    OutputType,
    StepSpec,
    metadata_json_from_authoring_form_fields,
)
from eneo.flows.flow_authoring_transcription import (
    AudioInputStep,
    apply_audio_transcription_defaults,
)
from eneo.flows.flow_authoring_variable_rewriting import (
    build_ref_to_order,
    rewrite_step_spec_variables,
)
from eneo.flows.flow_review_policy import FlowStepReviewPolicy


def _default_assistants_to_create() -> list[FlowDraftAssistantToCreate]:
    return []


def _default_compiled_steps() -> list[FlowDraftCompiledStep]:
    return []


class FlowDraftAssistantToCreate(BaseModel):
    plan_step_ref: str
    assistant_spec: AssistantSpec


class FlowDraftCompiledStep(BaseModel):
    plan_step_ref: str
    step_order: int
    user_description: str | None
    input_source: FlowInputSource
    input_type: FlowInputType
    output_mode: FlowOutputMode
    output_type: OutputType
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
    compiled_steps: list[FlowDraftCompiledStep] = Field(
        default_factory=_default_compiled_steps
    )
    metadata_json: FlowPersistedJsonObject | None = None


@dataclass(frozen=True, slots=True)
class FlowDraftMaterializationResult:
    flow_id: UUID
    flow_name: str
    draft_revision: int
    steps_created: int


def compile_flow_draft_changeset(
    spec: FlowDraftSpecCore,
    *,
    default_transcription_model_id: UUID | None = None,
) -> FlowDraftChangeSet:
    """The new draft ``spec`` describes: one new assistant per step, and the
    steps reading each other by their runtime aliases."""

    referenced = next(
        (step.existing_step_ref for step in spec.steps if step.existing_step_ref),
        None,
    )
    if referenced is not None:
        raise FlowAuthoringRefusalException(
            "Create flow commands cannot reference existing steps.",
            code=FlowAuthoringRefusalCode.INVALID_EXISTING_STEP_REF,
            context={
                "reason": "create_cannot_use_existing_step_ref",
                "existing_step_ref": referenced,
            },
        )
    ref_to_order = build_ref_to_order(spec.steps)
    assistants_to_create: list[FlowDraftAssistantToCreate] = []
    compiled_steps: list[FlowDraftCompiledStep] = []
    for index, step_spec in enumerate(spec.steps):
        rewritten_spec = rewrite_step_spec_variables(step_spec, ref_to_order)
        assistants_to_create.append(
            FlowDraftAssistantToCreate(
                plan_step_ref=step_spec.plan_step_ref,
                assistant_spec=rewritten_spec.assistant_spec,
            )
        )
        compiled_steps.append(
            _compile_new_step(step_spec=rewritten_spec, step_order=index + 1)
        )
    return FlowDraftChangeSet(
        flow_name=spec.flow_name,
        flow_description=spec.flow_description,
        assistants_to_create=assistants_to_create,
        compiled_steps=compiled_steps,
        metadata_json=build_flow_draft_metadata_json(
            spec=spec,
            steps=compiled_steps,
            default_transcription_model_id=default_transcription_model_id,
        ),
    )


def build_flow_draft_metadata_json(
    *,
    spec: FlowDraftSpecCore,
    steps: Sequence[AudioInputStep],
    default_transcription_model_id: UUID | None = None,
) -> FlowPersistedJsonObject | None:
    metadata: FlowPersistedJsonObject = {}
    form_metadata = metadata_json_from_authoring_form_fields(spec.form_fields)
    if form_metadata is not None:
        metadata["form_schema"] = form_metadata["form_schema"]
    metadata = (
        apply_audio_transcription_defaults(
            metadata=metadata if metadata else None,
            steps=steps,
            default_transcription_model_id=default_transcription_model_id,
        )
        or {}
    )
    return metadata if metadata else None


def _compile_new_step(
    *,
    step_spec: StepSpec,
    step_order: int,
) -> FlowDraftCompiledStep:
    return FlowDraftCompiledStep(
        plan_step_ref=step_spec.plan_step_ref,
        step_order=step_order,
        user_description=step_spec.name,
        input_source=FlowInputSource(step_spec.input_source.value),
        input_type=FlowInputType(step_spec.input_type.value),
        output_mode=FlowOutputMode(step_spec.output_mode.value),
        output_type=OutputType(step_spec.output_type.value),
        input_bindings=step_spec.input_bindings,
        input_contract=step_spec.input_contract,
        output_contract=step_spec.output_contract,
        input_config=step_spec.input_config,
        output_config=step_spec.output_config,
        review_policy=step_spec.review_policy,
    )
