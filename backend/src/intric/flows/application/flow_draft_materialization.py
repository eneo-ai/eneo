from __future__ import annotations

import enum
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, Field

from intric.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from intric.flows.enums import FlowInputSource, FlowInputType, FlowOutputMode
from intric.flows.flow_authoring_runtime_input import resolve_runtime_input_config
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    MCPPolicy,
    OutputType,
    StepSpec,
)
from intric.flows.flow_authoring_transcription import (
    apply_audio_transcription_defaults,
)
from intric.flows.flow_authoring_variable_rewriting import (
    build_ref_to_order,
    rewrite_step_spec_variables,
)
from intric.flows.flow_review_policy import FlowStepReviewPolicy
from intric.main.exceptions import BadRequestException


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
    mcp_policy: MCPPolicy
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
    steps_created: int
    steps_updated: int
    steps_removed: int


def compile_flow_draft_changeset(
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    *,
    default_transcription_model_id: UUID | None = None,
) -> FlowDraftChangeSet:
    existing_by_ref: dict[str, FlowStep] = {}
    if current_flow:
        for step in current_flow.steps:
            existing_by_ref[f"existing_step_{step.step_order}"] = step

    ref_to_order = build_ref_to_order(spec.steps)
    referenced_existing_refs: set[str] = set()
    assistants_to_create: list[FlowDraftAssistantToCreate] = []
    assistants_to_update: list[FlowDraftAssistantToUpdate] = []
    compiled_steps: list[FlowDraftCompiledStep] = []

    for index, step_spec in enumerate(spec.steps):
        step_order = index + 1
        existing_step = _resolve_existing_step(step_spec, existing_by_ref)
        rewritten_spec = rewrite_step_spec_variables(step_spec, ref_to_order)

        if existing_step is not None:
            referenced_existing_refs.add(step_spec.existing_step_ref or "")
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
        for ref, existing_step in existing_by_ref.items():
            if ref not in referenced_existing_refs:
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
    return step_spec.model_copy(update={"output_config": existing_step.output_config})


def build_flow_draft_metadata_json(
    *,
    spec: FlowDraftSpecCore,
    current_flow: Flow | None,
    default_transcription_model_id: UUID | None = None,
) -> FlowPersistedJsonObject | None:
    metadata: FlowPersistedJsonObject = {}
    if current_flow and current_flow.metadata_json:
        metadata = dict(current_flow.metadata_json)

    if spec.form_fields is not None:
        fields: list[FlowPersistedJsonObject] = []
        for field in spec.form_fields:
            field_dict: FlowPersistedJsonObject = {
                "name": field.name,
                "type": field.type,
                "label": field.label,
                "required": field.required,
            }
            if field.options is not None:
                field_dict["options"] = field.options
            fields.append(field_dict)
        metadata["form_schema"] = {"fields": fields}

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
        mcp_policy=MCPPolicy(step_spec.mcp_policy.value),
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
        mcp_policy=MCPPolicy(effective_spec.mcp_policy.value),
        input_bindings=effective_spec.input_bindings,
        input_contract=effective_spec.input_contract,
        output_contract=effective_spec.output_contract,
        input_config=resolve_runtime_input_config(
            step_spec=effective_spec,
            existing_input_config=existing_step.input_config,
        ),
        output_config=effective_spec.output_config,
        review_policy=effective_spec.review_policy,
    )
