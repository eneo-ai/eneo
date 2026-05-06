from __future__ import annotations

from intric.flows.ai_builder.ai_builder_edit_effective_steps import (
    apply_effective_step_operation,
    build_effective_step_states,
    resolve_insert_index,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
)
from intric.flows.ai_builder.ai_builder_models import InputSource, InputType
from intric.flows.domain.flow import FlowStep

_FILE_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}


def fill_edit_draft_mechanics(
    draft: FlowEditDraft,
    *,
    current_steps: list[FlowStep],
) -> FlowEditDraft:
    effective_steps = build_effective_step_states(current_steps)
    changed = False
    filled_operations: list[StepEditOperation] = []

    for operation in draft.operations:
        filled_operation = operation
        if operation.op == "add" and operation.add_payload is not None:
            insert_index = resolve_insert_index(
                op=operation,
                working_steps=effective_steps,
            )
            add_payload = _fill_add_payload_mechanics(
                operation.add_payload,
                insert_index=insert_index,
            )
            if add_payload != operation.add_payload:
                changed = True
                filled_operation = operation.model_copy(
                    update={"add_payload": add_payload}
                )

        filled_operations.append(filled_operation)
        apply_effective_step_operation(
            op=filled_operation, working_steps=effective_steps
        )

    if not changed:
        return draft
    return draft.model_copy(update={"operations": filled_operations})


def _fill_add_payload_mechanics(
    payload: AddStepPayload,
    *,
    insert_index: int,
) -> AddStepPayload:
    updates: dict[str, object] = {}
    input_source = payload.input_source
    if insert_index == 0 and input_source != InputSource.FLOW_INPUT:
        input_source = InputSource.FLOW_INPUT
        updates["input_source"] = InputSource.FLOW_INPUT

    if (
        insert_index != 0
        or input_source != InputSource.FLOW_INPUT
        or payload.input_type not in _FILE_INPUT_TYPES
    ):
        return payload.model_copy(update=updates) if updates else payload

    if not payload.runtime_upload:
        updates["runtime_upload"] = True
    if "runtime_required" not in payload.model_fields_set:
        updates["runtime_required"] = True

    if not updates:
        return payload
    return payload.model_copy(update=updates)
