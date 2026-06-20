from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from intric.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_input_reference_instruction_hint,
    compile_new_step_draft,
    compile_review_policy,
    compile_step_input_bindings,
    derive_new_step_output_mode,
    make_plan_step_ref,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    NewStepDraft,
    PreviousFieldRef,
)
from intric.flows.ai_builder.ai_builder_primary_input_fields import (
    remove_primary_runtime_input_shadow_names,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import AIBuilderResourceCatalog
from intric.flows.application.flow_draft_materialization import (
    validate_existing_step_ref_coverage,
)
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
    strip_inapplicable_completion_model,
)
from intric.flows.flow_review_policy import FlowStepReviewMode


class AssistantSpecPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instructions: str | None = None
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    mcp_tool_refs: list[str] = Field(default_factory=list)


class ModifyExistingStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["modify"] = "modify"
    existing_step_ref: str
    name: str | None = None
    assistant_spec: AssistantSpecPatch | None = None
    mcp_policy: MCPPolicy | None = None
    input_source: InputSource | None = None
    input_type: InputType | None = None
    output_mode: OutputMode | None = None
    output_type: OutputType | None = None
    input_bindings: FlowPersistedJsonObject | None = None
    input_contract: FlowPersistedJsonObject | None = None
    output_contract: FlowPersistedJsonObject | None = None
    input_config: FlowPersistedJsonObject | None = None
    output_config: FlowPersistedJsonObject | None = None
    review_mode: FlowStepReviewMode | None = None
    uses_form_fields: list[str] | None = None
    uses_previous_fields: list[PreviousFieldRef] | None = None
    document_delivery_mode: DocumentDeliveryMode | None = None


class AddStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["add"] = "add"
    step: NewStepDraft


OrderedEditStep = Annotated[ModifyExistingStep | AddStep, Field(discriminator="kind")]


class OrderedEditProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_name: str | None = None
    flow_description: str | None = None
    steps: list[OrderedEditStep]
    removed_existing_step_refs: frozenset[str] = Field(default_factory=frozenset)
    form_fields: list[FormFieldSpec] | None = None


def flow_step_to_authoring_spec(
    step: FlowStep,
    plan_ref: str,
    *,
    assistant_snapshots: AssistantAuthoringSnapshots | None = None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_ref,
        existing_step_ref=f"existing_step_{step.step_order}",
        name=step.user_description or f"Step {step.step_order}",
        assistant_spec=_resolve_existing_assistant_spec(
            step=step,
            assistant_snapshots=assistant_snapshots,
            resource_catalog=resource_catalog,
        ),
        input_source=InputSource(step.input_source),
        input_type=InputType(step.input_type),
        output_mode=OutputMode(step.output_mode),
        output_type=OutputType(step.output_type),
        mcp_policy=MCPPolicy(step.mcp_policy),
        input_bindings=step.input_bindings,
        input_contract=step.input_contract,
        output_contract=step.output_contract,
        input_config=step.input_config,
        output_config=step.output_config,
        review_policy=step.review_policy,
    )


def flow_steps_to_authoring_specs(steps: list[FlowStep]) -> list[StepSpec]:
    # Use builder StepSpec vocabulary for current-flow signature comparison.
    return [
        flow_step_to_authoring_spec(
            step,
            plan_ref=f"existing_step_{step.step_order}",
        )
        for step in steps
    ]


def compile_ordered_edit_proposal(
    *,
    base_spec: FlowDraftSpecCore,
    proposal: OrderedEditProposal,
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
        if item.kind == "add":
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
        compiled = compile_existing_step_modification(
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
        "output_mode",
        "output_type",
        "mcp_policy",
        "input_bindings",
        "input_contract",
        "output_contract",
        "input_config",
        "output_config",
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


def compile_existing_step_modification(
    existing: StepSpec,
    patch: ModifyExistingStep,
    *,
    prior_steps: list[StepSpec],
    primary_runtime_input_type: InputType | None = None,
) -> StepSpec:
    step = apply_existing_step_patch(existing, patch)
    fields = patch.model_fields_set

    if "uses_previous_fields" in fields or "uses_form_fields" in fields:
        uses_form_fields = remove_primary_runtime_input_shadow_names(
            field_names=patch.uses_form_fields or [],
            runtime_input_type=primary_runtime_input_type,
        )
        uses_previous_fields = patch.uses_previous_fields or []
        input_bindings = compile_step_input_bindings(
            input_source=step.input_source,
            input_type=step.input_type,
            uses_form_fields=uses_form_fields,
            uses_previous_fields=uses_previous_fields,
            uses_previous_outputs=[],
            prior_steps=prior_steps,
        )
        updates: dict[str, object | None] = {}
        if "input_bindings" not in fields:
            updates["input_bindings"] = input_bindings
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
        if updates:
            step = step.model_copy(update=updates)

    if "output_mode" not in fields:
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
    output_mode_draft = NewStepDraft(
        name=step.name or step.plan_step_ref,
        instructions="Derive output mode.",
        input_source=step.input_source,
        input_type=step.input_type,
        output_type=step.output_type,
        document_delivery_mode=(
            document_delivery_mode
            if document_delivery_mode is not None
            else _document_delivery_mode_for_existing_step(step)
        ),
    )
    return derive_new_step_output_mode(output_mode_draft)


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

    mcp_server_refs = existing.mcp_server_refs
    if "mcp_server_refs" in patched_fields:
        mcp_server_refs = patch.mcp_server_refs

    mcp_tool_refs = existing.mcp_tool_refs
    if "mcp_tool_refs" in patched_fields:
        mcp_tool_refs = patch.mcp_tool_refs

    patch_selects_knowledge = "knowledge_refs" in patched_fields and bool(
        patch.knowledge_refs
    )
    patch_selects_mcp = (
        "mcp_server_refs" in patched_fields and bool(patch.mcp_server_refs)
    ) or ("mcp_tool_refs" in patched_fields and bool(patch.mcp_tool_refs))
    if patch_selects_knowledge:
        mcp_server_refs = []
        mcp_tool_refs = []
    elif patch_selects_mcp:
        knowledge_refs = []

    return AssistantSpec(
        instructions=instructions,
        model_ref=model_ref,
        knowledge_refs=knowledge_refs,
        mcp_server_refs=mcp_server_refs,
        mcp_tool_refs=mcp_tool_refs,
    )


def _resolve_existing_assistant_spec(
    *,
    step: FlowStep,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
    resource_catalog: AIBuilderResourceCatalog | None,
) -> AssistantSpec:
    if not assistant_snapshots:
        return AssistantSpec(instructions="")

    snapshot = assistant_snapshots.get(step.assistant_id)
    if snapshot is None:
        return AssistantSpec(instructions="")

    if resource_catalog is None:
        if (
            snapshot.model is None
            and not snapshot.knowledge_refs
            and not snapshot.mcp_server_refs
            and not snapshot.mcp_tool_refs
        ):
            return AssistantSpec(instructions=snapshot.instructions)
        raise ValueError(
            "Resource catalog is required to translate assistant snapshots."
        )
    return resource_catalog.assistant_spec_from_snapshot(snapshot)


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
    proposal: OrderedEditProposal,
) -> str:
    if "flow_name" not in proposal.model_fields_set:
        return base_spec.flow_name
    if proposal.flow_name is None or not proposal.flow_name.strip():
        raise ValueError("Flow name cannot be cleared.")
    return proposal.flow_name.strip()


def _resolve_flow_description(
    base_spec: FlowDraftSpecCore,
    proposal: OrderedEditProposal,
) -> str:
    if "flow_description" not in proposal.model_fields_set:
        return base_spec.flow_description
    return (
        "" if proposal.flow_description is None else proposal.flow_description.strip()
    )


__all__ = [
    "AddStep",
    "AssistantSpecPatch",
    "ModifyExistingStep",
    "OrderedEditProposal",
    "compile_existing_step_modification",
    "compile_ordered_edit_proposal",
    "flow_step_to_authoring_spec",
    "flow_steps_to_authoring_specs",
    "merge_assistant_spec_patch",
]
