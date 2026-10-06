"""Admit typed local edit commands and lower them into a complete compiler draft."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    PreviousFieldRef,
    PreviousOutputRef,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep,
    AssistantSpecPatch,
    FlowInputFieldIntent,
    ModifyExistingStep,
    OrderedEditProposal,
    ProposalStructuredFieldIntent,
    SemanticStepArguments,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import step_name_key
from eneo.flows.flow_authoring_spec import InputSource, InputType, OutputType
from eneo.flows.flow_review_policy import FlowStepReviewMode


class SavedStepTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["saved"] = "saved"
    existing_step_ref: str = Field(min_length=1)


class AddedStepTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["added"] = "added"
    local_id: str = Field(min_length=1)


StepTarget = Annotated[SavedStepTarget | AddedStepTarget, Field(discriminator="kind")]


class EditFieldRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producer: StepTarget
    field_path: str
    label: str | None = None


class EditOutputRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producer: StepTarget
    label: str | None = None


class StartPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["start"] = "start"


class AfterPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["after"] = "after"
    target: StepTarget


EditPlacement = Annotated[StartPlacement | AfterPlacement, Field(discriminator="kind")]


class EditAssistantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instructions: str | None = None
    knowledge_refs: list[str] | None = None


class EditModifyOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["modify"] = "modify"
    existing_step_ref: str = Field(min_length=1)
    name: str | None = None
    assistant_spec: EditAssistantPatch | None = None
    input_source: InputSource | None = None
    input_type: InputType | None = None
    output_type: OutputType | None = None
    output_fields: list[ProposalStructuredFieldIntent] | None = None
    review_mode: FlowStepReviewMode | Literal["none"] | None = None
    uses_form_fields: list[str] | None = None
    uses_previous_fields: list[EditFieldRead] | None = None
    document_delivery_mode: DocumentDeliveryMode | None = None

    @property
    def authored_fields(self) -> frozenset[str]:
        fields = {
            name
            for name in self.model_fields_set
            if name not in {"kind", "existing_step_ref"}
            and getattr(self, name) is not None
        }
        if self.assistant_spec is not None and not self.assistant_spec.model_dump(
            exclude_none=True, exclude_unset=True
        ):
            fields.discard("assistant_spec")
        return frozenset(fields)


class EditNewStepArguments(SemanticStepArguments):
    output_type: OutputType | None = None
    uses_previous_fields: list[EditFieldRead] | None = None
    uses_previous_outputs: list[EditOutputRead] | None = None

    @field_validator("review_mode", mode="before")
    @classmethod
    def _clear_review(cls, value: object) -> object:
        return None if value == "none" else value


class EditAddOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["add"] = "add"
    local_id: str = Field(min_length=1)
    placement: EditPlacement
    step: EditNewStepArguments


class EditRemoveOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["remove"] = "remove"
    existing_step_ref: str = Field(min_length=1)


class EditMoveOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["move"] = "move"
    existing_step_ref: str = Field(min_length=1)
    placement: EditPlacement


class EditFlowModifyOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["modify_flow"] = "modify_flow"
    flow_name: str | None = None
    flow_description: str | None = None
    form_fields: list[FlowInputFieldIntent] | None = None


EditOperation = Annotated[
    EditModifyOperation
    | EditAddOperation
    | EditRemoveOperation
    | EditMoveOperation
    | EditFlowModifyOperation,
    Field(discriminator="kind"),
]


class EditCommands(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_rationale: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    operations: list[EditOperation]


EditCommandRejectionReason = Literal[
    "unknown_edit_step",
    "duplicate_edit_operation",
    "conflicting_edit_operations",
    "unknown_edit_anchor",
    "removed_edit_anchor",
    "self_edit_move",
    "duplicate_local_step",
    "edit_step_name_collision",
    "invalid_edit_read",
]


class EditCommandRejection(Exception):
    def __init__(self, reason: EditCommandRejectionReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def parse_edit_commands(arguments: object) -> EditCommands:
    return EditCommands.model_validate(arguments)


def lower_edit_commands(
    commands: EditCommands,
    *,
    baseline_names: Mapping[str, str],
) -> OrderedEditProposal:
    """Mutate only a private identity index; the saved graph is never written."""
    order: list[SavedStepTarget | AddedStepTarget] = [
        SavedStepTarget(existing_step_ref=ref) for ref in baseline_names
    ]
    modifications: dict[str, EditModifyOperation] = {}
    additions: dict[str, EditAddOperation] = {}
    flow_modification: EditFlowModifyOperation | None = None
    removed: set[str] = set()
    moved: set[str] = set()
    removal_targets = {
        op.existing_step_ref
        for op in commands.operations
        if isinstance(op, EditRemoveOperation)
    }
    for op in commands.operations:
        if isinstance(op, EditFlowModifyOperation):
            if flow_modification is not None:
                raise EditCommandRejection(
                    "duplicate_edit_operation", "Modify the flow only once."
                )
            flow_modification = op
            continue
        if isinstance(op, EditAddOperation):
            if op.local_id in additions:
                raise EditCommandRejection(
                    "duplicate_local_step", f"Local id {op.local_id!r} is already used."
                )
            target = AddedStepTarget(local_id=op.local_id)
            position = _placement_index(op.placement, order, removal_targets, target)
            order.insert(position, target)
            additions[op.local_id] = op
            continue
        ref = op.existing_step_ref
        target = SavedStepTarget(existing_step_ref=ref)
        if target not in order:
            raise EditCommandRejection(
                "unknown_edit_step", f"Unknown or removed saved step {ref!r}."
            )
        if isinstance(op, EditModifyOperation):
            if ref in modifications:
                raise EditCommandRejection(
                    "duplicate_edit_operation", f"Modify step {ref!r} only once."
                )
            if ref in removal_targets:
                raise EditCommandRejection(
                    "conflicting_edit_operations",
                    f"Step {ref!r} cannot be modified and removed.",
                )
            modifications[ref] = op
        elif isinstance(op, EditRemoveOperation):
            removed.add(ref)
            order.remove(target)
        else:
            if ref in moved or ref in removal_targets:
                raise EditCommandRejection(
                    "conflicting_edit_operations",
                    f"Step {ref!r} cannot be moved twice or removed.",
                )
            position = _placement_index(op.placement, order, removal_targets, target)
            old_position = order.index(target)
            order.pop(old_position)
            order.insert(position - int(old_position < position), target)
            moved.add(ref)

    names: dict[str, list[StepTarget]] = {}
    for ref, name in baseline_names.items():
        if ref not in removed:
            key = step_name_key(
                modifications[ref].name or name if ref in modifications else name
            )
            names.setdefault(key, []).append(SavedStepTarget(existing_step_ref=ref))
    for addition in additions.values():
        key = step_name_key(addition.step.name)
        if targets := names.get(key):
            identities = json.dumps([target.model_dump() for target in targets])
            raise EditCommandRejection(
                "edit_step_name_collision",
                f"Added name {addition.step.name!r} is already used by {identities}. "
                "Use modify or move for saved work instead of reconstructing it "
                "as add. Give genuinely new work a distinct name, or omit a "
                "duplicate add command.",
            )
        names[key] = [AddedStepTarget(local_id=addition.local_id)]

    positions = {target: index + 1 for index, target in enumerate(order)}
    steps: list[ModifyExistingStep | AddStep] = []
    for target in order:
        if isinstance(target, SavedStepTarget):
            op = modifications.get(target.existing_step_ref)
            steps.append(
                _lower_modify(op, positions, target)
                if op is not None
                else ModifyExistingStep(existing_step_ref=target.existing_step_ref)
            )
        else:
            steps.append(
                AddStep(
                    step=_lower_add(additions[target.local_id].step, positions, target)
                )
            )
    payload = commands.model_dump(
        exclude={"operations"}, exclude_none=True, exclude_unset=True
    )
    if flow_modification is not None:
        payload.update(
            flow_modification.model_dump(
                exclude={"kind", "form_fields"}, exclude_none=True, exclude_unset=True
            )
        )
        if flow_modification.form_fields is not None:
            payload["form_fields"] = [
                field.model_copy(update={"provenance": "model_proposed"})
                for field in flow_modification.form_fields
            ]
    return OrderedEditProposal.model_validate(
        {**payload, "steps": steps, "removed_existing_step_refs": frozenset(removed)}
    )


def _placement_index(
    placement: EditPlacement,
    order: Sequence[SavedStepTarget | AddedStepTarget],
    removed: set[str],
    self_target: SavedStepTarget | AddedStepTarget,
) -> int:
    if isinstance(placement, StartPlacement):
        return 0
    target = placement.target
    if target == self_target:
        raise EditCommandRejection(
            "self_edit_move", "A step cannot be placed after itself."
        )
    if isinstance(target, SavedStepTarget) and target.existing_step_ref in removed:
        raise EditCommandRejection(
            "removed_edit_anchor", "Placement must not depend on a removed step."
        )
    if target not in order:
        raise EditCommandRejection(
            "unknown_edit_anchor",
            "Placement must name a saved or previously added step.",
        )
    return order.index(target) + 1


def _read_position(
    producer: StepTarget,
    positions: Mapping[SavedStepTarget | AddedStepTarget, int],
    consumer: StepTarget,
) -> int:
    index = positions.get(producer)
    if index is None or index >= positions[consumer]:
        raise EditCommandRejection(
            "invalid_edit_read",
            "A read must name a retained producer earlier than its consumer.",
        )
    return index


def _field_reads(
    reads: Sequence[EditFieldRead],
    positions: Mapping[SavedStepTarget | AddedStepTarget, int],
    consumer: StepTarget,
) -> list[PreviousFieldRef]:
    return [
        PreviousFieldRef(
            from_step=_read_position(read.producer, positions, consumer),
            field_path=read.field_path,
            label=read.label,
        )
        for read in reads
    ]


def _lower_modify(
    op: EditModifyOperation,
    positions: Mapping[SavedStepTarget | AddedStepTarget, int],
    target: StepTarget,
) -> ModifyExistingStep:
    payload = op.model_dump(
        exclude={
            "output_fields",
            "uses_previous_fields",
            "assistant_spec",
            "review_mode",
        },
        exclude_none=True,
        exclude_unset=True,
    )
    if op.assistant_spec is not None:
        patch = op.assistant_spec.model_dump(exclude_none=True, exclude_unset=True)
        if patch:
            payload["assistant_spec"] = AssistantSpecPatch.model_validate(patch)
    if op.output_fields is not None:
        payload["output_fields"] = [
            field.to_structured_field_draft() for field in op.output_fields
        ]
    if op.uses_previous_fields is not None:
        payload["uses_previous_fields"] = _field_reads(
            op.uses_previous_fields, positions, target
        )
    if op.review_mode is not None:
        payload["review_mode"] = None if op.review_mode == "none" else op.review_mode
    return ModifyExistingStep.model_validate(payload)


def _lower_add(
    step: EditNewStepArguments,
    positions: Mapping[SavedStepTarget | AddedStepTarget, int],
    target: StepTarget,
) -> SemanticStepIntent:
    payload = step.model_dump(
        exclude={"output_fields", "uses_previous_fields", "uses_previous_outputs"},
        exclude_none=True,
    )
    payload["output_fields"] = (
        [field.to_structured_field_draft() for field in step.output_fields]
        if step.output_fields
        else None
    )
    payload["uses_previous_fields"] = _field_reads(
        step.uses_previous_fields or [], positions, target
    )
    payload["uses_previous_outputs"] = [
        PreviousOutputRef(
            from_step=_read_position(read.producer, positions, target),
            label=read.label,
        )
        for read in step.uses_previous_outputs or []
    ]
    return SemanticStepIntent.model_validate(payload)
