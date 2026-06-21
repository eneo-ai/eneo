from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_new_step_mechanics import (
    validate_new_step_mechanics,
)
from intric.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_draft_field_path,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.flow_authoring_spec import (
    OutputType,
)


def validate_create_draft(draft: FlowCreateDraft) -> SpecValidationResult:
    result = SpecValidationResult()

    if not draft.steps:
        result.add_error(
            step_ref=None,
            code="empty_steps",
            message="Create draft must contain at least one step.",
        )
        return result

    _validate_form_fields(draft, result)

    for index, step in enumerate(draft.steps):
        step_ref = f"steps[{index}]"
        validate_new_step_mechanics(
            step=step,
            step_ref=step_ref,
            step_index=index,
            available_form_fields={form_field.name for form_field in draft.form_fields},
            result=result,
        )
        _validate_previous_field_references(
            draft=draft,
            step_index=index,
            result=result,
        )
        _validate_previous_output_references(
            draft=draft,
            step_index=index,
            result=result,
        )

    return result


def _validate_form_fields(draft: FlowCreateDraft, result: SpecValidationResult) -> None:
    seen_names: set[str] = set()
    for index, field in enumerate(draft.form_fields):
        if field.name in seen_names:
            result.add_error(
                step_ref=f"form_fields[{index}]",
                code="duplicate_form_field",
                message=f"Duplicate form field name '{field.name}'.",
            )
        seen_names.add(field.name)
        if field.type in {"select", "multiselect"} and not field.options:
            result.add_error(
                step_ref=f"form_fields[{index}]",
                code="select_field_missing_options",
                message="select and multiselect form fields require options.",
            )


def _validate_previous_field_references(
    *,
    draft: FlowCreateDraft,
    step_index: int,
    result: SpecValidationResult,
) -> None:
    step = draft.steps[step_index]
    step_ref = f"steps[{step_index}]"
    for field_ref in step.uses_previous_fields:
        target_index = field_ref.from_step - 1
        if target_index < 0 or target_index >= step_index:
            result.add_error(
                step_ref=step_ref,
                code="invalid_previous_field_source",
                message="uses_previous_fields must point at an earlier step in the create draft.",
            )
            continue
        target_step = draft.steps[target_index]
        if target_step.output_type != OutputType.JSON:
            result.add_error(
                step_ref=step_ref,
                code="previous_field_source_requires_json_output",
                message=(
                    "uses_previous_fields can only reference earlier steps that produce JSON output."
                ),
            )
            continue
        if target_step.output_fields is None:
            result.add_error(
                step_ref=step_ref,
                code="previous_field_source_missing_output_fields",
                message=(
                    "uses_previous_fields requires the referenced earlier step to declare output_fields."
                ),
            )
            continue
        if (
            missing_draft_field_path(target_step.output_fields, field_ref.field_path)
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


def _validate_previous_output_references(
    *,
    draft: FlowCreateDraft,
    step_index: int,
    result: SpecValidationResult,
) -> None:
    step = draft.steps[step_index]
    step_ref = f"steps[{step_index}]"
    for output_ref in step.uses_previous_outputs:
        target_index = output_ref.from_step - 1
        if target_index < 0 or target_index >= step_index:
            result.add_error(
                step_ref=step_ref,
                code="invalid_previous_output_source",
                message=(
                    "uses_previous_outputs must point at an earlier step in the "
                    "create draft."
                ),
            )
            continue
        target_step = draft.steps[target_index]
        if target_step.output_type != OutputType.TEXT:
            result.add_error(
                step_ref=step_ref,
                code="previous_output_source_requires_text_output",
                message=(
                    "uses_previous_outputs can only reference earlier steps that "
                    "produce text output."
                ),
            )
