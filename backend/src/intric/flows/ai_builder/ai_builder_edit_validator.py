"""Edit-mode validators for the AI Builder.

Validates FlowEditDraft operations BEFORE compilation to catch structural
errors early and provide clear feedback to the LLM for self-correction.
"""

from __future__ import annotations

from typing import Any, cast

from intric.flows.ai_builder.ai_builder_edit_models import (
    AddStepPayload,
    FlowEditDraft,
    StepEditOperation,
    StepPatch,
)
from intric.flows.ai_builder.ai_builder_models import OutputType
from intric.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)
from intric.flows.flow import FlowStep


def validate_edit_draft(
    draft: FlowEditDraft,
    valid_step_refs: list[str],
    current_steps: list[FlowStep] | None = None,
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

    for i, op in enumerate(draft.operations):
        op_label = f"operations[{i}]"

        if op.op == "add":
            _validate_add_op(op, valid_step_refs, op_label, result, current_steps)
        elif op.op == "modify":
            _validate_modify_op(op, valid_step_refs, op_label, result, current_steps)
        elif op.op == "remove":
            _validate_remove_op(op, valid_step_refs, op_label, result)

        # Check duplicate target_ref
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
        placement = op.placement.position if op.placement is not None else "append"
        anchor_ref = op.placement.anchor_ref if op.placement is not None else None
        max_prior_order = len(current_steps)
        if placement == "before" and anchor_ref is not None:
            max_prior_order = max(0, _step_order_from_ref(anchor_ref) - 1)
        elif placement == "after" and anchor_ref is not None:
            max_prior_order = _step_order_from_ref(anchor_ref)
        _validate_add_previous_field_references(
            step=op.add_payload,
            max_prior_order=max_prior_order,
            current_steps=current_steps,
            step_ref=None,
            result=result,
        )


def _validate_modify_op(
    op: StepEditOperation,
    valid_refs: list[str],
    label: str,
    result: SpecValidationResult,
    current_steps: list[FlowStep] | None,
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

    # Warn on type downgrades
    if op.patch is not None and op.patch.input_type is not None:
        from intric.flows.ai_builder.ai_builder_models import InputType

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
        _validate_patch_previous_field_references(
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


def _validate_patch_previous_field_references(
    *,
    patch: StepPatch,
    current_steps: list[FlowStep],
    step_ref: str | None,
    result: SpecValidationResult,
) -> None:
    if not patch.uses_previous_fields:
        return
    for field_ref in patch.uses_previous_fields:
        target_index = field_ref.from_step - 1
        if target_index < 0 or target_index >= len(current_steps):
            result.add_error(
                step_ref=step_ref,
                code="invalid_previous_field_source",
                message="uses_previous_fields must point at an earlier step in the current flow.",
            )
            continue
        target_step = current_steps[target_index]
        if target_step.output_type != OutputType.JSON.value:
            result.add_error(
                step_ref=step_ref,
                code="previous_field_source_requires_json_output",
                message=(
                    "uses_previous_fields can only reference earlier steps that produce JSON output."
                ),
            )
            continue
        output_contract = (
            target_step.output_contract
            if isinstance(target_step.output_contract, dict)
            else None
        )
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
            _missing_output_contract_path(output_contract, field_ref.field_path)
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


def _validate_add_previous_field_references(
    *,
    step: AddStepPayload,
    max_prior_order: int,
    current_steps: list[FlowStep],
    step_ref: str | None,
    result: SpecValidationResult,
) -> None:
    if not getattr(step, "uses_previous_fields", None):
        return
    for field_ref in step.uses_previous_fields:
        if field_ref.from_step < 1 or field_ref.from_step > max_prior_order:
            result.add_error(
                step_ref=step_ref,
                code="invalid_previous_field_source",
                message="uses_previous_fields must point at an earlier step in the edited flow order.",
            )
            continue
        target_step: FlowStep = current_steps[field_ref.from_step - 1]
        if target_step.output_type != OutputType.JSON.value:
            result.add_error(
                step_ref=step_ref,
                code="previous_field_source_requires_json_output",
                message=(
                    "uses_previous_fields can only reference earlier steps that produce JSON output."
                ),
            )
            continue
        output_contract = (
            target_step.output_contract
            if isinstance(target_step.output_contract, dict)
            else None
        )
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
            _missing_output_contract_path(output_contract, field_ref.field_path)
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


def _missing_output_contract_path(
    contract: dict[str, Any], field_path: str
) -> str | None:
    current: dict[str, Any] | None = contract
    traversed: list[str] = []
    for part in field_path.split("."):
        traversed.append(part)
        if not isinstance(current, dict):
            return ".".join(traversed)
        current_dict = current
        schema_type = current_dict.get("type")
        if schema_type == "array":
            if part.isdigit():
                current = current_dict.get("items")
                if not isinstance(current, dict):
                    return ".".join(traversed)
                continue
            current = current_dict.get("items")
            if not isinstance(current, dict):
                return ".".join(traversed)
        properties = current.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            return ".".join(traversed)
        properties_dict = cast(dict[str, Any], properties)
        next_current: Any = properties_dict[part]
        current = (
            cast(dict[str, Any], next_current)
            if isinstance(next_current, dict)
            else None
        )
    return None


def _step_order_from_ref(step_ref: str) -> int:
    raw = step_ref.removeprefix("existing_step_")
    return int(raw) if raw.isdigit() else 0
