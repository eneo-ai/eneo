from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_input_reference_instruction_hint,
    compile_new_step_draft,
    compile_review_policy,
    compile_step_input_bindings,
    derive_input_contract,
    derive_output_mode,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    NewStepDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep as IntentAddStep,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AssistantSpecPatch,
    ModifyExistingStep,
    OrderedEditProposal,
    SemanticStepIntent,
)
from eneo.flows.application.flow_draft_materialization import (
    validate_existing_step_ref_coverage,
)
from eneo.flows.flow_authoring_runtime_input import resolve_runtime_input_config
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
    strip_inapplicable_completion_model,
)


class MaterializedAddStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["add"] = "add"
    step: NewStepDraft


MaterializedOrderedEditStep = Annotated[
    ModifyExistingStep | MaterializedAddStep,
    Field(discriminator="kind"),
]


class MaterializedOrderedEditProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_rationale: str
    assumptions: list[str] = Field(default_factory=list)
    flow_name: str | None = None
    flow_description: str | None = None
    steps: list[MaterializedOrderedEditStep]
    removed_existing_step_refs: frozenset[str] = Field(default_factory=frozenset)
    form_fields: list[FormFieldSpec] | None = None


def materialize_ordered_edit_proposal(
    proposal: OrderedEditProposal,
    *,
    primary_runtime_input_type: InputType | None = None,
    primary_runtime_required: bool = True,
) -> MaterializedOrderedEditProposal:
    payload = proposal.model_dump(
        mode="python",
        exclude={"steps"},
        exclude_unset=True,
    )
    payload["steps"] = [
        _materialize_ordered_edit_step(
            item,
            step_index=index,
            primary_runtime_input_type=primary_runtime_input_type,
            primary_runtime_required=primary_runtime_required,
        )
        for index, item in enumerate(proposal.steps)
    ]
    return MaterializedOrderedEditProposal.model_validate(payload)


def _materialize_ordered_edit_step(
    item: object,
    *,
    step_index: int,
    primary_runtime_input_type: InputType | None,
    primary_runtime_required: bool,
) -> object:
    if not isinstance(item, IntentAddStep):
        return item
    return MaterializedAddStep(
        step=_new_step_draft_from_semantic_intent(
            item.step,
            step_index=step_index,
            primary_runtime_input_type=primary_runtime_input_type,
            primary_runtime_required=primary_runtime_required,
        )
    )


def _new_step_draft_from_semantic_intent(
    step: SemanticStepIntent,
    *,
    step_index: int,
    primary_runtime_input_type: InputType | None,
    primary_runtime_required: bool,
) -> NewStepDraft:
    if step_index == 0 and primary_runtime_input_type is not None:
        is_primary_runtime_step = True
        input_type = primary_runtime_input_type
    else:
        is_primary_runtime_step = False
        input_type = InputType.TEXT
    return NewStepDraft(
        name=step.name,
        instructions=step.instructions,
        input_type=input_type,
        output_type=step.output_type or OutputType.TEXT,
        runtime_required=primary_runtime_required if is_primary_runtime_step else False,
        model_ref=step.model_ref,
        knowledge_refs=list(step.knowledge_refs),
        uses_form_fields=list(step.uses_form_fields),
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
        output_fields=step.output_fields,
    )


def compile_ordered_edit_proposal(
    *,
    base_spec: FlowDraftSpecCore,
    proposal: MaterializedOrderedEditProposal,
) -> FlowDraftSpecCore:
    base_by_ref = {
        step.existing_step_ref: step
        for step in base_spec.steps
        if step.existing_step_ref is not None
    }
    preserved_refs: list[str] = []
    compiled_steps: list[StepSpec] = []

    for index, item in enumerate(proposal.steps):
        plan_ref = make_plan_step_ref(index)
        if isinstance(item, MaterializedAddStep):
            compiled_steps.append(
                compile_new_step_draft(
                    step_draft=item.step,
                    plan_step_ref=plan_ref,
                    prior_steps=compiled_steps,
                )
            )
            continue

        base_step = base_by_ref.get(item.existing_step_ref)
        if base_step is None:
            preserved_refs.append(item.existing_step_ref)
            continue
        preserved_refs.append(item.existing_step_ref)
        compiled = _compile_existing_step_modification(
            base_step,
            item,
            prior_steps=compiled_steps,
        )
        compiled_steps.append(compiled.model_copy(update={"plan_step_ref": plan_ref}))

    validate_existing_step_ref_coverage(
        current_refs=set(base_by_ref),
        preserved_refs=preserved_refs,
        removed_existing_step_refs=proposal.removed_existing_step_refs,
    )

    return FlowDraftSpecCore(
        flow_name=_resolve_flow_name(base_spec, proposal),
        flow_description=_resolve_flow_description(base_spec, proposal),
        steps=compiled_steps,
        form_fields=(
            proposal.form_fields
            if "form_fields" in proposal.model_fields_set
            else base_spec.form_fields
        ),
        document_body_writer_step_refs=_document_body_writer_step_refs(
            base_spec=base_spec,
            compiled_steps=compiled_steps,
        ),
    )


def apply_existing_step_patch(
    existing: StepSpec,
    patch: ModifyExistingStep,
) -> StepSpec:
    updates: dict[str, object] = {}
    fields = patch.model_fields_set

    if "name" in fields:
        if patch.name is None or not patch.name.strip():
            raise ValueError("Step name cannot be cleared.")
        updates["name"] = patch.name.strip()
    for field_name in (
        "input_source",
        "input_type",
        "output_type",
        "output_contract",
    ):
        if field_name in fields:
            updates[field_name] = getattr(patch, field_name)
    if "review_mode" in fields:
        updates["review_policy"] = compile_review_policy(patch.review_mode)
    if "assistant_spec" in fields:
        if patch.assistant_spec is None:
            raise ValueError("Assistant spec cannot be cleared.")
        updates["assistant_spec"] = merge_assistant_spec_patch(
            existing.assistant_spec,
            patch.assistant_spec,
        )

    return strip_inapplicable_completion_model(existing.model_copy(update=updates))


def _compile_existing_step_modification(
    existing: StepSpec,
    patch: ModifyExistingStep,
    *,
    prior_steps: list[StepSpec],
) -> StepSpec:
    step = apply_existing_step_patch(existing, patch)
    fields = patch.model_fields_set

    if fields & {
        "input_source",
        "input_type",
        "uses_previous_fields",
        "uses_form_fields",
    }:
        uses_form_fields = patch.uses_form_fields or []
        uses_previous_fields = patch.uses_previous_fields or []
        input_bindings = compile_step_input_bindings(
            input_source=step.input_source,
            input_type=step.input_type,
            uses_form_fields=uses_form_fields,
            uses_previous_fields=uses_previous_fields,
            uses_previous_outputs=[],
            prior_steps=prior_steps,
        )
        input_contract = derive_input_contract(
            input_source=step.input_source,
            input_type=step.input_type,
            prior_steps=prior_steps,
            input_bindings=input_bindings,
        )
        updates: dict[str, object | None] = {
            "input_bindings": input_bindings,
            "input_contract": input_contract,
        }
        if input_bindings is None:
            hint = compile_input_reference_instruction_hint(
                uses_previous_fields=uses_previous_fields,
                uses_form_fields=uses_form_fields,
            )
            if hint:
                updates["assistant_spec"] = step.assistant_spec.model_copy(
                    update={
                        "instructions": f"{step.assistant_spec.instructions}\n\n{hint}"
                    }
                )
        step = step.model_copy(update=updates)
        input_config = resolve_runtime_input_config(step_spec=step)
        if input_config != step.input_config:
            step = step.model_copy(update={"input_config": input_config})

    output_mode = _derive_existing_step_output_mode(
        step,
        document_delivery_mode=patch.document_delivery_mode,
    )
    if output_mode != step.output_mode:
        step = step.model_copy(update={"output_mode": output_mode})

    return strip_inapplicable_completion_model(step)


def _derive_existing_step_output_mode(
    step: StepSpec,
    *,
    document_delivery_mode: DocumentDeliveryMode | None,
) -> OutputMode:
    return derive_output_mode(
        input_type=step.input_type,
        output_type=step.output_type,
        document_delivery_mode=(
            document_delivery_mode
            if document_delivery_mode is not None
            else _document_delivery_mode_for_existing_step(step)
        ),
    )


def _document_delivery_mode_for_existing_step(
    step: StepSpec,
) -> DocumentDeliveryMode:
    if (
        step.output_mode == OutputMode.TEMPLATE_FILL
        and step.output_type == OutputType.DOCX
    ):
        return "template_fill"
    if step.output_type in {OutputType.DOCX, OutputType.PDF}:
        return "generated"
    return "not_applicable"


def merge_assistant_spec_patch(
    existing: AssistantSpec,
    patch: AssistantSpecPatch,
) -> AssistantSpec:
    patched_fields = patch.model_fields_set

    instructions = existing.instructions
    if "instructions" in patched_fields:
        if patch.instructions is None or not patch.instructions.strip():
            raise ValueError("Assistant instructions cannot be cleared.")
        instructions = patch.instructions.strip()

    model_ref = existing.model_ref
    if "model_ref" in patched_fields:
        model_ref = patch.model_ref

    knowledge_refs = existing.knowledge_refs
    if "knowledge_refs" in patched_fields:
        knowledge_refs = patch.knowledge_refs

    return AssistantSpec(
        instructions=instructions,
        model_ref=model_ref,
        knowledge_refs=knowledge_refs,
    )


def _document_body_writer_step_refs(
    *,
    base_spec: FlowDraftSpecCore,
    compiled_steps: list[StepSpec],
) -> tuple[str, ...] | None:
    base_refs = base_spec.document_body_writer_step_refs
    if base_refs is None:
        return None

    base_step_by_plan_ref = {step.plan_step_ref: step for step in base_spec.steps}
    next_ref_by_existing_ref = {
        step.existing_step_ref: step.plan_step_ref
        for step in compiled_steps
        if step.existing_step_ref is not None
    }
    refs: list[str] = []
    for base_ref in base_refs:
        base_step = base_step_by_plan_ref.get(base_ref)
        if base_step is None or base_step.existing_step_ref is None:
            continue
        next_ref = next_ref_by_existing_ref.get(base_step.existing_step_ref)
        if next_ref is not None:
            refs.append(next_ref)
    return tuple(refs) or None


def _resolve_flow_name(
    base_spec: FlowDraftSpecCore,
    proposal: MaterializedOrderedEditProposal,
) -> str:
    if "flow_name" not in proposal.model_fields_set:
        return base_spec.flow_name
    if proposal.flow_name is None or not proposal.flow_name.strip():
        raise ValueError("Flow name cannot be cleared.")
    return proposal.flow_name.strip()


def _resolve_flow_description(
    base_spec: FlowDraftSpecCore,
    proposal: MaterializedOrderedEditProposal,
) -> str:
    if "flow_description" not in proposal.model_fields_set:
        return base_spec.flow_description
    return (
        "" if proposal.flow_description is None else proposal.flow_description.strip()
    )


__all__ = [
    "MaterializedAddStep",
    "MaterializedOrderedEditProposal",
    "MaterializedOrderedEditStep",
    "compile_ordered_edit_proposal",
    "materialize_ordered_edit_proposal",
    "merge_assistant_spec_patch",
]
