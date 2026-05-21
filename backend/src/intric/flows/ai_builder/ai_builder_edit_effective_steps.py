from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    StepEditOperation,
    StepPatch,
)
from intric.flows.ai_builder.ai_builder_new_step_compiler import compile_output_contract
from intric.flows.domain.flow import FlowStep
from intric.flows.flow_authoring_spec import (
    OutputType,
)


@dataclass
class EffectiveStepState:
    """Minimal step view used for edit-time previous-field validation."""

    ref: str | None
    output_type: str
    output_contract: dict[str, Any] | None


def build_effective_step_states(
    current_steps: list[FlowStep],
) -> list[EffectiveStepState]:
    return [
        EffectiveStepState(
            ref=f"existing_step_{step.step_order}",
            output_type=step.output_type,
            output_contract=(
                step.output_contract if isinstance(step.output_contract, dict) else None
            ),
        )
        for step in sorted(current_steps, key=lambda step: step.step_order)
    ]


def resolve_insert_index(
    *,
    op: StepEditOperation,
    working_steps: list[EffectiveStepState],
) -> int:
    if op.placement is None or op.placement.position == "append":
        return len(working_steps)
    if op.placement.anchor_ref is None:
        return len(working_steps)
    for index, step in enumerate(working_steps):
        if step.ref != op.placement.anchor_ref:
            continue
        if op.placement.position == "before":
            return index
        return index + 1
    return len(working_steps)


def apply_effective_step_operation(
    *,
    op: StepEditOperation,
    working_steps: list[EffectiveStepState],
) -> None:
    if op.op == "remove" and op.target_ref is not None:
        remove_effective_step(working_steps, op.target_ref)
        return
    if op.op == "modify" and op.target_ref is not None and op.patch is not None:
        apply_patch_to_effective_step(working_steps, op.target_ref, op.patch)
        return
    if op.op == "add" and op.add_payload is not None:
        working_steps.insert(
            resolve_insert_index(op=op, working_steps=working_steps),
            preview_add_effective_step(op.add_payload),
        )


def preview_add_effective_step(add_payload: AddStepPayload) -> EffectiveStepState:
    return EffectiveStepState(
        ref=None,
        output_type=add_payload.output_type.value,
        output_contract=compile_output_contract(add_payload.output_fields),
    )


def apply_patch_to_effective_step(
    working_steps: list[EffectiveStepState],
    target_ref: str,
    patch: StepPatch,
) -> None:
    for step in working_steps:
        if step.ref != target_ref:
            continue
        if "output_type" in patch.model_fields_set and patch.output_type is not None:
            step.output_type = patch.output_type.value
        if "output_contract" in patch.model_fields_set:
            step.output_contract = (
                patch.output_contract
                if isinstance(patch.output_contract, dict)
                else None
            )
        return


def effective_step_index(
    working_steps: list[EffectiveStepState],
    target_ref: str,
) -> int | None:
    for index, step in enumerate(working_steps):
        if step.ref == target_ref:
            return index
    return None


def remove_effective_step(
    working_steps: list[EffectiveStepState],
    target_ref: str,
) -> None:
    index = effective_step_index(working_steps, target_ref)
    if index is None:
        return
    working_steps.pop(index)


def output_type_is_json(output_type: str) -> bool:
    return output_type == OutputType.JSON.value
