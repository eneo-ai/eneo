"""Edit-mode validators for the AI Builder.

Validates FlowEditDraft operations BEFORE compilation to catch structural
errors early and provide clear feedback to the LLM for self-correction.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    StepEditOperation,
)
from intric.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)


def validate_edit_draft(
    draft: FlowEditDraft,
    valid_step_refs: list[str],
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
            _validate_add_op(op, valid_step_refs, op_label, result)
        elif op.op == "modify":
            _validate_modify_op(op, valid_step_refs, op_label, result)
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


def _validate_modify_op(
    op: StepEditOperation,
    valid_refs: list[str],
    label: str,
    result: SpecValidationResult,
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
