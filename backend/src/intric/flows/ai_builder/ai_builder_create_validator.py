from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_models import InputSource, InputType, OutputType
from intric.flows.ai_builder.ai_builder_new_step_compiler import (
    derive_new_step_output_mode,
)
from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    supports_step_io_mode_combo,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult

_FILE_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}


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
        if index == 0 and step.input_source != InputSource.FLOW_INPUT:
            result.add_error(
                step_ref=step_ref,
                code="first_step_invalid_source",
                message="Step 1 must use input_source 'flow_input'.",
            )
        if index > 0 and step.input_source == InputSource.FLOW_INPUT:
            result.add_error(
                step_ref=step_ref,
                code="multiple_flow_input",
                message="Only the first create-draft step may use input_source 'flow_input'.",
            )
        if (
            step.input_source != InputSource.FLOW_INPUT
            and step.input_type in _FILE_INPUT_TYPES
        ):
            result.add_error(
                step_ref=step_ref,
                code="media_source_mismatch",
                message=(
                    "audio/document/file input types are only valid with input_source 'flow_input'."
                ),
            )
        if (
            step.input_source == InputSource.FLOW_INPUT
            and step.input_type in _FILE_INPUT_TYPES
            and not step.runtime_upload
        ):
            result.add_error(
                step_ref=step_ref,
                code="file_flow_input_requires_runtime_upload",
                message=(
                    "flow_input steps with audio/document/file input_type require runtime_upload=true."
                ),
            )
        if step.runtime_upload and (
            step.input_source != InputSource.FLOW_INPUT
            or step.input_type not in _FILE_INPUT_TYPES
        ):
            result.add_error(
                step_ref=step_ref,
                code="runtime_upload_requires_file_flow_input",
                message=(
                    "runtime_upload is only valid for flow_input steps with audio/document/file input."
                ),
            )
        if not step.runtime_upload and (
            step.runtime_required or step.runtime_max_files is not None
        ):
            result.add_error(
                step_ref=step_ref,
                code="runtime_upload_flags_without_runtime_upload",
                message=(
                    "runtime_required and runtime_max_files require runtime_upload=true."
                ),
            )
        if (
            step.document_delivery_mode == "template_fill"
            and step.output_type != OutputType.DOCX
        ):
            result.add_error(
                step_ref=step_ref,
                code="template_fill_requires_docx",
                message="document_delivery_mode 'template_fill' requires output_type 'docx'.",
            )
        if step.document_delivery_mode != "not_applicable" and step.output_type not in {
            OutputType.DOCX,
            OutputType.PDF,
        }:
            result.add_error(
                step_ref=step_ref,
                code="document_delivery_mode_type_mismatch",
                message=(
                    "document_delivery_mode is only valid for docx or pdf outputs."
                ),
            )
        if step.citations_requested and step.output_type != OutputType.TEXT:
            result.add_error(
                step_ref=step_ref,
                code="citations_require_text_output",
                message="citations_requested is only valid for text output steps.",
            )
        if step.citations_requested and step.input_type == InputType.AUDIO:
            result.add_error(
                step_ref=step_ref,
                code="citations_require_llm_text_step",
                message=(
                    "citations_requested cannot be used on audio transcription steps."
                ),
            )
        if step.output_fields is not None and step.output_type != OutputType.JSON:
            result.add_error(
                step_ref=step_ref,
                code="output_fields_require_json_output",
                message="output_fields are only valid when output_type is 'json'.",
            )
        if (
            step.input_source == InputSource.ALL_PREVIOUS_STEPS
            and step.input_type == InputType.JSON
        ):
            result.add_error(
                step_ref=step_ref,
                code="json_incompatible_with_all_previous_steps",
                message="input_type 'json' is incompatible with input_source 'all_previous_steps'.",
            )
        if not supports_step_io_mode_combo(
            input_type=step.input_type.value,
            output_type=step.output_type.value,
            output_mode=derive_new_step_output_mode(step).value,
        ):
            result.add_error(
                step_ref=step_ref,
                code="unsupported_step_io_combo",
                message="The draft requests an unsupported input/output/output-mode combination.",
            )
        missing_fields = [
            field_name
            for field_name in step.uses_form_fields
            if field_name
            not in {form_field.variable_name for form_field in draft.form_fields}
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
        _validate_previous_field_references(
            draft=draft,
            step_index=index,
            result=result,
        )

    return result


def _validate_form_fields(draft: FlowCreateDraft, result: SpecValidationResult) -> None:
    seen_names: set[str] = set()
    for index, field in enumerate(draft.form_fields):
        if field.variable_name in seen_names:
            result.add_error(
                step_ref=f"form_fields[{index}]",
                code="duplicate_form_field",
                message=f"Duplicate form field variable_name '{field.variable_name}'.",
            )
        seen_names.add(field.variable_name)
        if field.field_type in {"select", "multiselect"} and not field.options:
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
            _resolve_structured_field_path(
                target_step.output_fields,
                field_ref.field_path,
            )
            is None
        ):
            result.add_error(
                step_ref=step_ref,
                code="unknown_previous_field_reference",
                message=(
                    f"uses_previous_fields references unknown structured field path '{field_ref.field_path}' "
                    f"on step {field_ref.from_step}."
                ),
            )


def _resolve_structured_field_path(
    fields: list[StructuredFieldDraft],
    field_path: str,
) -> StructuredFieldDraft | None:
    current_fields = fields
    current_field: StructuredFieldDraft | None = None
    expecting_index = False
    for segment in field_path.split("."):
        if expecting_index:
            if not segment.isdigit():
                return None
            if current_field is None or current_field.item_fields is None:
                return None
            current_fields = current_field.item_fields
            expecting_index = False
            continue

        current_field = next(
            (field for field in current_fields if field.name == segment), None
        )
        if current_field is None:
            return None
        if current_field.field_type == "array":
            expecting_index = True
        elif current_field.fields is not None:
            current_fields = current_field.fields
        else:
            current_fields = []

    return None if expecting_index else current_field
