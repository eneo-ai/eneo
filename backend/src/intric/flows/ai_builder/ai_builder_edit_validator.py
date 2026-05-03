"""Edit-mode validators for the AI Builder.

Validates FlowEditDraft operations BEFORE compilation to catch structural
errors early and provide clear feedback to the LLM for self-correction.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_edit_effective_steps import (
    EffectiveStepState,
    apply_effective_step_operation,
    build_effective_step_states,
    effective_step_index,
    output_type_is_json,
    resolve_insert_index,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
)
from intric.flows.ai_builder.ai_builder_form_fields import (
    effective_form_field_names,
)
from intric.flows.ai_builder.ai_builder_models import (
    InputType,
)
from intric.flows.ai_builder.ai_builder_new_step_mechanics import (
    validate_new_step_mechanics,
)
from intric.flows.ai_builder.ai_builder_new_step_models import PreviousFieldRef
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    supports_step_io_mode_combo,
)
from intric.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_structured_output_path,
)
from intric.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)
from intric.flows.domain.flow import FlowStep


def validate_edit_draft(
    draft: FlowEditDraft,
    valid_step_refs: list[str],
    current_steps: list[FlowStep] | None = None,
    current_metadata_json: dict[str, object] | None = None,
) -> SpecValidationResult:
    """Validate edit draft operations before compilation.

    Args:
        draft: The edit draft from the LLM.
        valid_step_refs: Valid existing step refs (e.g. ["existing_step_1", "existing_step_2"]).

    Returns:
        SpecValidationResult with any errors/warnings.
    """
    result = SpecValidationResult()
    seen_targets: set[str] = set()
    effective_steps = build_effective_step_states(current_steps or [])
    available_form_fields = effective_form_field_names(
        current_metadata_json,
        draft.form_operations,
    )
    removed_step_orders = {
        _step_order_from_ref(op.target_ref)
        for op in draft.operations
        if op.op == "remove"
        and op.target_ref in valid_step_refs
        and _step_order_from_ref(op.target_ref) > 0
    }

    for i, op in enumerate(draft.operations):
        op_label = f"operations[{i}]"

        if op.op == "add":
            _validate_add_op(
                op,
                valid_step_refs,
                op_label,
                result,
                current_steps,
                removed_step_orders,
                available_form_fields,
                effective_steps,
            )
        elif op.op == "modify":
            _validate_modify_op(
                op,
                valid_step_refs,
                op_label,
                result,
                current_steps,
                removed_step_orders,
                available_form_fields,
                effective_steps,
            )
        elif op.op == "remove":
            _validate_remove_op(op, valid_step_refs, op_label, result)

        apply_effective_step_operation(op=op, working_steps=effective_steps)

        if op.target_ref is not None:
            if op.target_ref in seen_targets:
                result.add_error(
                    step_ref=op.target_ref,
                    code="duplicate_target_ref",
                    message=(
                        f"{op_label}: target_ref '{op.target_ref}' appears in "
                        f"multiple operations. Each step can only be targeted once."
                    ),
                )
            seen_targets.add(op.target_ref)

    return result


def _validate_add_op(
    op: StepEditOperation,
    valid_refs: list[str],
    label: str,
    result: SpecValidationResult,
    current_steps: list[FlowStep] | None,
    removed_step_orders: set[int],
    available_form_fields: set[str],
    effective_steps: list[EffectiveStepState],
) -> None:
    if op.target_ref is not None:
        result.add_error(
            step_ref=None,
            code="add_with_target_ref",
            message=(
                f"{label}: 'add' operations must NOT have target_ref. "
                f"To modify an existing step, use op='modify' instead."
            ),
        )

    if op.add_payload is None:
        result.add_error(
            step_ref=None,
            code="add_missing_payload",
            message=f"{label}: 'add' operations require add_payload with a typed new-step draft.",
        )

    if op.placement is not None and op.placement.position != "append":
        if op.placement.anchor_ref is None:
            result.add_error(
                step_ref=None,
                code="placement_missing_anchor",
                message=(
                    f"{label}: placement position '{op.placement.position}' "
                    f"requires anchor_ref. Valid refs: {valid_refs}"
                ),
            )
        elif op.placement.anchor_ref not in valid_refs:
            result.add_error(
                step_ref=None,
                code="invalid_placement_anchor",
                message=(
                    f"{label}: anchor_ref '{op.placement.anchor_ref}' is not a valid "
                    f"existing step. Valid refs: {valid_refs}"
                ),
            )

    if op.add_payload is not None and current_steps is not None:
        insert_index = resolve_insert_index(op=op, working_steps=effective_steps)
        validate_new_step_mechanics(
            step=op.add_payload,
            step_ref=None,
            step_index=insert_index,
            available_form_fields=available_form_fields,
            result=result,
        )
        _validate_add_previous_field_references(
            step=op.add_payload,
            max_prior_order=insert_index,
            effective_steps=effective_steps,
            step_ref=None,
            result=result,
            removed_step_orders=removed_step_orders,
        )


def _validate_modify_op(
    op: StepEditOperation,
    valid_refs: list[str],
    label: str,
    result: SpecValidationResult,
    current_steps: list[FlowStep] | None,
    removed_step_orders: set[int],
    available_form_fields: set[str],
    effective_steps: list[EffectiveStepState],
) -> None:
    if op.target_ref is None:
        result.add_error(
            step_ref=None,
            code="modify_missing_target",
            message=(
                f"{label}: 'modify' operations require target_ref. "
                f"Valid refs: {valid_refs}"
            ),
        )
    elif op.target_ref not in valid_refs:
        result.add_error(
            step_ref=op.target_ref,
            code="invalid_target_ref",
            message=(
                f"{label}: target_ref '{op.target_ref}' does not match any "
                f"existing step. Valid refs: {valid_refs}"
            ),
        )

    if op.patch is None:
        result.add_error(
            step_ref=op.target_ref,
            code="modify_missing_patch",
            message=f"{label}: 'modify' operations require a patch with at least one field.",
        )

    if op.patch is not None:
        _validate_form_field_references(
            uses_form_fields=op.patch.uses_form_fields,
            available_form_fields=available_form_fields,
            step_ref=op.target_ref,
            result=result,
        )

    if op.patch is not None and op.patch.input_type is not None:
        if op.patch.input_type == InputType.FILE:
            result.add_warning(
                step_ref=op.target_ref,
                code="type_downgrade_risk",
                message=(
                    f"{label}: changing input_type to 'file' may lose type-specific "
                    f"processing. Consider 'document' or 'audio' instead."
                ),
            )
    if op.patch is not None and current_steps is not None:
        target_step_index = (
            effective_step_index(effective_steps, op.target_ref)
            if op.target_ref is not None
            else None
        )
        if target_step_index is not None and op.target_ref in valid_refs:
            _validate_patch_previous_field_references(
                patch=op.patch,
                effective_steps=effective_steps,
                step_ref=op.target_ref,
                result=result,
                target_step_order=target_step_index + 1,
                removed_step_orders=removed_step_orders,
            )
            _validate_patch_output_mode(
                patch=op.patch,
                current_steps=current_steps,
                step_ref=op.target_ref,
                result=result,
            )


def _validate_remove_op(
    op: StepEditOperation,
    valid_refs: list[str],
    label: str,
    result: SpecValidationResult,
) -> None:
    if op.target_ref is None:
        result.add_error(
            step_ref=None,
            code="remove_missing_target",
            message=(
                f"{label}: 'remove' operations require target_ref. "
                f"Valid refs: {valid_refs}"
            ),
        )
    elif op.target_ref not in valid_refs:
        result.add_error(
            step_ref=op.target_ref,
            code="invalid_target_ref",
            message=(
                f"{label}: target_ref '{op.target_ref}' does not match any "
                f"existing step. Valid refs: {valid_refs}"
            ),
        )


def _validate_form_field_references(
    *,
    uses_form_fields: list[str] | None,
    available_form_fields: set[str],
    step_ref: str | None,
    result: SpecValidationResult,
) -> None:
    if not uses_form_fields:
        return
    missing_fields = [
        field_name
        for field_name in uses_form_fields
        if field_name not in available_form_fields
    ]
    if missing_fields:
        result.add_error(
            step_ref=step_ref,
            code="unknown_form_field_reference",
            message=(
                "uses_form_fields references unknown form fields: "
                + ", ".join(missing_fields)
                + "."
            ),
        )


def _validate_patch_output_mode(
    *,
    patch: StepPatch,
    current_steps: list[FlowStep],
    step_ref: str | None,
    result: SpecValidationResult,
) -> None:
    if patch.output_mode is None or step_ref is None:
        return

    current_step = _current_step_for_ref(current_steps, step_ref)
    if current_step is None:
        return

    input_type_value = _enum_value(patch.input_type or current_step.input_type)
    output_type_value = _enum_value(patch.output_type or current_step.output_type)
    output_mode_value = patch.output_mode.value
    if supports_step_io_mode_combo(
        input_type=input_type_value,
        output_type=output_type_value,
        output_mode=output_mode_value,
    ):
        return

    result.add_error(
        step_ref=step_ref,
        code="unsupported_step_io_combo",
        message=(
            f"output_mode '{output_mode_value}' is not valid with "
            f"input_type '{input_type_value}' and output_type '{output_type_value}'."
        ),
    )


def _current_step_for_ref(
    current_steps: list[FlowStep],
    step_ref: str,
) -> FlowStep | None:
    step_order = _step_order_from_ref(step_ref)
    for current_step in current_steps:
        if current_step.step_order == step_order:
            return current_step
    return None


def _enum_value(value: object) -> str:
    raw_value = getattr(value, "value", value)
    return str(raw_value)


def _validate_patch_previous_field_references(
    *,
    patch: StepPatch,
    effective_steps: list[EffectiveStepState],
    step_ref: str | None,
    result: SpecValidationResult,
    target_step_order: int,
    removed_step_orders: set[int],
) -> None:
    if not patch.uses_previous_fields:
        return
    _validate_previous_field_references(
        field_refs=patch.uses_previous_fields,
        max_prior_order=target_step_order - 1,
        effective_steps=effective_steps,
        step_ref=step_ref,
        result=result,
        removed_step_orders=removed_step_orders,
        earlier_step_message=(
            "uses_previous_fields must point at an earlier step in the current flow."
        ),
    )


def _validate_add_previous_field_references(
    *,
    step: AddStepPayload,
    max_prior_order: int,
    effective_steps: list[EffectiveStepState],
    step_ref: str | None,
    result: SpecValidationResult,
    removed_step_orders: set[int],
) -> None:
    if not step.uses_previous_fields:
        return
    _validate_previous_field_references(
        field_refs=step.uses_previous_fields,
        max_prior_order=min(max_prior_order, len(effective_steps)),
        effective_steps=effective_steps,
        step_ref=step_ref,
        result=result,
        removed_step_orders=removed_step_orders,
        earlier_step_message=(
            "uses_previous_fields must point at an earlier step in the edited flow order."
        ),
    )


def _validate_previous_field_references(
    *,
    field_refs: list[PreviousFieldRef],
    max_prior_order: int,
    effective_steps: list[EffectiveStepState],
    step_ref: str | None,
    result: SpecValidationResult,
    removed_step_orders: set[int],
    earlier_step_message: str,
) -> None:
    for field_ref in field_refs:
        if field_ref.from_step < 1 or field_ref.from_step > max_prior_order:
            result.add_error(
                step_ref=step_ref,
                code="invalid_previous_field_source",
                message=earlier_step_message,
            )
            continue
        if field_ref.from_step in removed_step_orders:
            result.add_error(
                step_ref=step_ref,
                code="removed_previous_field_source",
                message=(
                    "uses_previous_fields cannot reference a step that is being removed in the same edit draft."
                ),
            )
            continue
        target_step = effective_steps[field_ref.from_step - 1]
        if not output_type_is_json(target_step.output_type):
            result.add_error(
                step_ref=step_ref,
                code="previous_field_source_requires_json_output",
                message=(
                    "uses_previous_fields can only reference earlier steps that produce JSON output."
                ),
            )
            continue
        output_contract = target_step.output_contract
        if output_contract is None:
            result.add_error(
                step_ref=step_ref,
                code="previous_field_source_missing_output_fields",
                message=(
                    "uses_previous_fields requires the referenced earlier step to declare structured output fields."
                ),
            )
            continue
        if (
            missing_structured_output_path(
                output_contract,
                field_ref.field_path,
                require_array_index=True,
            )
            is not None
        ):
            result.add_error(
                step_ref=step_ref,
                code="unknown_previous_field_reference",
                message=(
                    f"uses_previous_fields references unknown structured field path '{field_ref.field_path}' "
                    f"on step {field_ref.from_step}."
                ),
            )


def _step_order_from_ref(step_ref: str) -> int:
    raw = step_ref.removeprefix("existing_step_")
    return int(raw) if raw.isdigit() else 0
