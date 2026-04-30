"""Validation for AI Builder flow specs.

Two-pass validation:
1. Hard validation — blocks invalid plans (chaining rules, type compat, enums)
2. Quality lint — flags weak plans as warnings (shown on plan card)
"""

from __future__ import annotations

import jsonschema

from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.ai_builder.ai_builder_validation_flow_parity import (
    validate_flow_service_parity,
)
from intric.flows.ai_builder.ai_builder_validation_quality import (
    lint_all_previous_steps_overuse,
    lint_all_previous_with_specific_refs,
    lint_contract_fields_without_descriptions,
    lint_contract_instruction_alignment,
    lint_json_output_without_contract,
    lint_multi_goal_prompts,
    lint_previous_step_binding_without_previous_source,
    lint_single_step_flow,
    lint_unfiltered_structured_interpolation,
    lint_unused_form_fields,
    lint_vague_step_names,
)
from intric.flows.ai_builder.ai_builder_validation_references import (
    validate_variable_references,
)
from intric.flows.output_modes import transcribe_only_violation
from intric.flows.step_chain_rules import find_first_step_chain_violation

# ---------------------------------------------------------------------------
# Valid enum values (from DB constraints, excluding http_ which AI can't set)
# ---------------------------------------------------------------------------

_VALID_INPUT_SOURCES = {e.value for e in InputSource}
_VALID_INPUT_TYPES = {e.value for e in InputType}
_VALID_OUTPUT_MODES = {e.value for e in OutputMode}
_VALID_OUTPUT_TYPES = {e.value for e in OutputType}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_spec(
    spec: FlowDraftSpecCore,
    *,
    available_model_refs: set[str] | None = None,
    available_kb_refs: set[str] | None = None,
) -> SpecValidationResult:
    """Validate a FlowDraftSpecCore with hard validation + quality lint.

    Args:
        spec: The flow draft spec to validate.
        available_model_refs: Known model aliases (for reference validation).
        available_kb_refs: Known knowledge base aliases (for reference validation).

    Returns:
        SpecValidationResult with errors and warnings.
    """
    result = SpecValidationResult()

    if not spec.steps:
        result.add_error(
            step_ref=None,
            code="empty_steps",
            message="Flow must have at least one step.",
        )
        return result

    _validate_step_refs_unique(spec, result)
    _validate_step_names_unique(spec, result)
    _validate_chaining_rules(spec, result)
    _validate_type_compatibility(spec, result)
    _validate_enum_values(spec, result)
    _validate_transcribe_only(spec, result)
    _validate_template_fill(spec, result)
    _validate_contract_syntax(spec, result)
    _validate_contract_type_compat(spec, result)
    _validate_previous_step_json_contracts(spec, result)
    _validate_model_refs(spec, result, available_model_refs)
    _validate_kb_refs(spec, result, available_kb_refs)
    validate_flow_service_parity(spec, result)
    validate_variable_references(spec, result)

    # Quality lint (only if hard validation passes)
    if result.valid:
        lint_all_previous_steps_overuse(spec, result)
        lint_vague_step_names(spec, result)
        lint_multi_goal_prompts(spec, result)
        lint_single_step_flow(spec, result)
        lint_json_output_without_contract(spec, result)
        lint_contract_fields_without_descriptions(spec, result)
        lint_contract_instruction_alignment(spec, result)
        lint_unused_form_fields(spec, result)
        lint_all_previous_with_specific_refs(spec, result)
        lint_unfiltered_structured_interpolation(spec, result)
        lint_previous_step_binding_without_previous_source(spec, result)

    return result


# ---------------------------------------------------------------------------
# Hard validation checks
# ---------------------------------------------------------------------------


def _validate_step_refs_unique(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    seen: set[str] = set()
    for step in spec.steps:
        if step.plan_step_ref in seen:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="duplicate_step_ref",
                message=f"Duplicate plan_step_ref '{step.plan_step_ref}'.",
            )
        seen.add(step.plan_step_ref)


def _validate_step_names_unique(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    seen: set[str] = set()
    for step in spec.steps:
        normalized = step.name.strip().casefold()
        if not normalized:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="empty_step_name",
                message="Step name cannot be empty.",
            )
            continue
        if normalized in seen:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="duplicate_step_name",
                message=f"Duplicate step name '{step.name}' (case-insensitive).",
            )
        seen.add(normalized)


def _validate_chaining_rules(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    violation = find_first_step_chain_violation(_chain_shapes(spec))
    if violation is None:
        return

    step_ref = (
        spec.steps[violation.step_order - 1].plan_step_ref
        if violation.step_order <= len(spec.steps)
        else None
    )
    result.add_error(
        step_ref=step_ref,
        code=_map_chain_violation_code(violation.code),
        message=violation.message,
    )


def _validate_type_compatibility(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    steps = spec.steps
    for index, step in enumerate(steps):
        if step.input_source != InputSource.PREVIOUS_STEP or index == 0:
            continue
        previous = steps[index - 1]
        if (
            previous.output_type == OutputType.PDF
            and step.input_type == InputType.AUDIO
        ):
            result.add_error(
                step_ref=step.plan_step_ref,
                code="incompatible_type_chain",
                message=(
                    f"Incompatible type chain: previous step output '{previous.output_type.value}' "
                    f"cannot feed input '{step.input_type.value}'."
                ),
            )
        if (
            previous.output_type == OutputType.DOCX
            and step.input_type == InputType.JSON
        ):
            result.add_error(
                step_ref=step.plan_step_ref,
                code="incompatible_type_chain",
                message=(
                    f"Incompatible type chain: previous step output '{previous.output_type.value}' "
                    f"cannot feed input '{step.input_type.value}'."
                ),
            )


def _validate_enum_values(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for step in spec.steps:
        if step.input_source.value not in _VALID_INPUT_SOURCES:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_input_source",
                message=f"Unsupported input_source '{step.input_source.value}'.",
            )
        if step.input_type.value not in _VALID_INPUT_TYPES:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_input_type",
                message=f"Unsupported input_type '{step.input_type.value}'.",
            )
        if step.output_mode.value not in _VALID_OUTPUT_MODES:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_output_mode",
                message=f"Unsupported output_mode '{step.output_mode.value}'.",
            )
        if step.output_type.value not in _VALID_OUTPUT_TYPES:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_output_type",
                message=f"Unsupported output_type '{step.output_type.value}'.",
            )


def _validate_transcribe_only(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for i, step in enumerate(spec.steps):
        error = transcribe_only_violation(
            step_order=i + 1,
            input_type=step.input_type.value,
            output_type=step.output_type.value,
            output_mode=step.output_mode.value,
        )
        if error is not None:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="transcribe_only_violation",
                message=error,
            )


def _validate_template_fill(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for step in spec.steps:
        if step.output_mode != OutputMode.TEMPLATE_FILL:
            continue
        if step.output_type != OutputType.DOCX:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="template_fill_requires_docx",
                message="output_mode 'template_fill' requires output_type 'docx'.",
            )


def _validate_model_refs(
    spec: FlowDraftSpecCore,
    result: SpecValidationResult,
    available: set[str] | None,
) -> None:
    if available is None:
        return
    for step in spec.steps:
        ref = step.assistant_spec.model_ref
        if ref is not None and ref not in available:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="unknown_model_ref",
                message=f"Unknown model reference '{ref}'.",
            )


def _validate_kb_refs(
    spec: FlowDraftSpecCore,
    result: SpecValidationResult,
    available: set[str] | None,
) -> None:
    if available is None:
        return
    for step in spec.steps:
        for ref in step.assistant_spec.knowledge_refs:
            if ref not in available:
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="unknown_kb_ref",
                    message=f"Unknown knowledge base reference '{ref}'.",
                )


# ---------------------------------------------------------------------------
# Hard validation: contract syntax and type compatibility
# ---------------------------------------------------------------------------


def _validate_contract_syntax(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    """Validate JSON Schema syntax of contracts at plan time."""
    for step in spec.steps:
        for field_name, contract in [
            ("input_contract", step.input_contract),
            ("output_contract", step.output_contract),
        ]:
            if contract is None:
                continue
            try:
                jsonschema.Draft202012Validator.check_schema(contract)
            except jsonschema.SchemaError as e:
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code=f"invalid_{field_name}_schema",
                    message=f"Invalid {field_name} JSON Schema: {e.message}",
                )


def _validate_contract_type_compat(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    """Validate that contracts are compatible with step input/output types."""
    for step in spec.steps:
        if step.input_contract is not None and step.input_type not in (
            InputType.TEXT,
            InputType.JSON,
        ):
            result.add_error(
                step_ref=step.plan_step_ref,
                code="input_contract_type_mismatch",
                message=(
                    f"input_contract is only valid for input_type 'text' or 'json', "
                    f"not '{step.input_type.value}'."
                ),
            )
        if step.output_contract is not None and step.output_type == OutputType.TEXT:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="output_contract_type_mismatch",
                message="output_contract is not valid for output_type 'text'. Use 'json' for structured output.",
            )
        if (
            step.output_contract is not None
            and step.output_mode == OutputMode.TEMPLATE_FILL
        ):
            result.add_error(
                step_ref=step.plan_step_ref,
                code="output_contract_template_fill_incompatible",
                message="output_contract is not supported for output_mode 'template_fill'.",
            )


def _validate_previous_step_json_contracts(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for index, step in enumerate(spec.steps):
        if (
            index == 0
            or step.input_source != InputSource.PREVIOUS_STEP
            or step.input_type != InputType.JSON
        ):
            continue

        previous_step = spec.steps[index - 1]
        expected_contract = (
            previous_step.output_contract
            if previous_step.output_type == OutputType.JSON
            else None
        )
        if step.input_contract == expected_contract:
            continue

        result.add_error(
            step_ref=step.plan_step_ref,
            code="previous_step_json_contract_mismatch",
            message=(
                "previous_step JSON input_contract must match the previous "
                "step output_contract because the runtime passes that exact "
                "payload between steps."
            ),
        )


def _chain_shapes(spec: FlowDraftSpecCore) -> list[_StepChainShape]:
    return [
        _StepChainShape(
            step_order=index + 1,
            input_source=step.input_source.value,
            input_type=step.input_type.value,
            output_type=step.output_type.value,
        )
        for index, step in enumerate(spec.steps)
    ]


def _map_chain_violation_code(code: str) -> str:
    return {
        "typed_io_invalid_input_source_position": "first_step_invalid_source",
        "typed_io_multiple_flow_input_steps": "multiple_flow_input",
        "typed_io_flow_input_position_invalid": "flow_input_not_first",
        "typed_io_document_source_unsupported": "media_source_mismatch",
        "typed_io_audio_source_unsupported": "media_source_mismatch",
        "typed_io_file_source_unsupported": "media_source_mismatch",
        "typed_io_invalid_input_source_combination": "json_all_previous_incompatible",
        "typed_io_incompatible_type_chain": "incompatible_type_chain",
    }.get(code, "invalid_step_chain")


class _StepChainShape:
    def __init__(
        self, *, step_order: int, input_source: str, input_type: str, output_type: str
    ) -> None:
        self.step_order = step_order
        self.input_source = input_source
        self.input_type = input_type
        self.output_type = output_type
