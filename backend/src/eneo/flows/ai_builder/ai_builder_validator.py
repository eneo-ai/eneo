"""Validation for AI Builder flow specs."""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.ai_builder_validation_quality import (
    lint_all_previous_steps_overuse,
    lint_all_previous_with_specific_refs,
    lint_contract_instruction_alignment,
    lint_json_output_without_contract,
    lint_multi_goal_prompts,
    lint_shadowed_form_field_bare_references,
    lint_single_step_flow,
    lint_unfiltered_structured_interpolation,
    lint_unused_form_fields,
    lint_vague_step_names,
)
from eneo.flows.ai_builder.ai_builder_validation_references import (
    validate_variable_references,
)
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepGraphIssue,
    FlowStepValidationError,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    metadata_json_from_authoring_form_fields,
)
from eneo.flows.flow_authoring_variable_rewriting import (
    flow_step_validation_views_from_draft_spec,
)
from eneo.flows.flow_validators import (
    collect_step_graph_issues,
    validate_form_schema,
)
from eneo.flows.flow_validators_form import (
    validate_variable_alias_collisions_for_step_graph,
)
from eneo.flows.input_binding_contract_rules import (
    InputBindingContractError,
    duplicate_source_ref_expressions,
)
from eneo.main.exceptions import BadRequestException

_BUILDER_IGNORED_FLOW_VALIDATION_CODES: frozenset[FlowGraphIssueCode] = frozenset(
    {
        FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED,
        FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_REQUIRED,
    }
)
_BUILDER_IGNORED_FLOW_VALIDATION_EXCEPTION_CODES = frozenset(
    code.value for code in _BUILDER_IGNORED_FLOW_VALIDATION_CODES
)
_CANONICAL_GRAPH_CODE_TO_BUILDER_CODE: dict[FlowGraphIssueCode, str] = {
    FlowGraphIssueCode.AUDIO_DOCUMENT_TRANSCRIPT_CHAIN_INVALID: (
        "audio_document_transcript_chain_invalid"
    ),
    FlowGraphIssueCode.DUPLICATE_STEP_NAME: "duplicate_step_name",
    FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_INVALID: (
        "flow_audio_transcription_invalid"
    ),
    FlowGraphIssueCode.FLOW_HTTP_POST_OUTPUT_MUST_BE_TERMINAL: (
        "flow_http_post_output_must_be_terminal"
    ),
    FlowGraphIssueCode.FLOW_INPUT_BINDING_FUTURE_STEP_REFERENCE: (
        "input_binding_future_step_reference"
    ),
    FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE: (
        "input_binding_invalid_step_reference"
    ),
    FlowGraphIssueCode.FLOW_INPUT_BINDING_UNKNOWN_STEP_ORDER: (
        "input_binding_unknown_step_order"
    ),
    FlowGraphIssueCode.FLOW_INPUT_CONTRACT_INAPPLICABLE: (
        "input_contract_type_mismatch"
    ),
    FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_POSITION: (
        "first_step_invalid_source"
    ),
    FlowGraphIssueCode.TYPED_IO_MULTIPLE_FLOW_INPUT_STEPS: "multiple_flow_input",
    FlowGraphIssueCode.TYPED_IO_FLOW_INPUT_POSITION_INVALID: "flow_input_not_first",
    FlowGraphIssueCode.TYPED_IO_DOCUMENT_SOURCE_UNSUPPORTED: ("media_source_mismatch"),
    FlowGraphIssueCode.TYPED_IO_AUDIO_SOURCE_UNSUPPORTED: "media_source_mismatch",
    FlowGraphIssueCode.TYPED_IO_FILE_SOURCE_UNSUPPORTED: "media_source_mismatch",
    FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION: (
        "json_all_previous_incompatible"
    ),
    FlowGraphIssueCode.TYPED_IO_INCOMPATIBLE_TYPE_CHAIN: "incompatible_type_chain",
    FlowGraphIssueCode.TRANSCRIBE_ONLY_VIOLATION: "transcribe_only_violation",
    FlowGraphIssueCode.TEMPLATE_FILL_REQUIRES_DOCX: "template_fill_requires_docx",
    FlowGraphIssueCode.INVALID_INPUT_CONTRACT_SCHEMA: "invalid_input_contract_schema",
    FlowGraphIssueCode.INVALID_OUTPUT_CONTRACT_SCHEMA: (
        "invalid_output_contract_schema"
    ),
    FlowGraphIssueCode.INPUT_CONTRACT_TYPE_MISMATCH: "input_contract_type_mismatch",
    FlowGraphIssueCode.INPUT_CONTRACT_SOURCE_MISMATCH: "input_contract_type_mismatch",
    FlowGraphIssueCode.OUTPUT_CONTRACT_TYPE_MISMATCH: "output_contract_type_mismatch",
    FlowGraphIssueCode.OUTPUT_CONTRACT_TEMPLATE_FILL_INCOMPATIBLE: (
        "output_contract_template_fill_incompatible"
    ),
    FlowGraphIssueCode.UNSUPPORTED_INPUT_TYPE: "unsupported_input_type",
}
_CANONICAL_GRAPH_CODES_WITH_GENERIC_BUILDER_PRESENTATION: frozenset[
    FlowGraphIssueCode
] = frozenset(
    {
        FlowGraphIssueCode.DUPLICATE_STEP_ORDER,
        FlowGraphIssueCode.FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
        FlowGraphIssueCode.FLOW_REVIEW_POLICY_INVALID,
        FlowGraphIssueCode.FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED,
        FlowGraphIssueCode.FLOW_STEP_INVALID,
        FlowGraphIssueCode.STEP_ORDER_NOT_CONTIGUOUS,
        FlowGraphIssueCode.TYPED_IO_MISSING_PREVIOUS_STEP,
    }
)


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
    _validate_step_names_present(spec, result)
    _validate_model_refs(spec, result, available_model_refs)
    _validate_kb_refs(spec, result, available_kb_refs)
    _validate_source_refs_unique(spec, result)
    _validate_flow_service_rules(spec, result)
    validate_variable_references(spec, result)

    # Quality lint (only if hard validation passes)
    if result.valid:
        lint_all_previous_steps_overuse(spec, result)
        lint_vague_step_names(spec, result)
        lint_multi_goal_prompts(spec, result)
        lint_single_step_flow(spec, result)
        lint_json_output_without_contract(spec, result)
        lint_contract_instruction_alignment(spec, result)
        lint_unused_form_fields(spec, result)
        lint_shadowed_form_field_bare_references(spec, result)
        lint_all_previous_with_specific_refs(spec, result)
        lint_unfiltered_structured_interpolation(spec, result)

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


def _validate_step_names_present(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for step in spec.steps:
        normalized = step.name.strip().casefold()
        if not normalized:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="empty_step_name",
                message="Step name cannot be empty.",
            )


def _validate_source_refs_unique(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for step in spec.steps:
        try:
            duplicate_expressions = duplicate_source_ref_expressions(
                step.input_bindings
            )
        except InputBindingContractError as exc:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="invalid_source_refs",
                message=str(exc),
            )
            continue
        for expression in duplicate_expressions:
            result.add_error(
                step_ref=step.plan_step_ref,
                code="duplicate_source_ref",
                message=(
                    "input_bindings.source_refs contains duplicate material for "
                    f"{expression}."
                ),
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


def _validate_flow_service_rules(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    flow_steps = flow_step_validation_views_from_draft_spec(spec.steps)
    metadata_json = metadata_json_from_authoring_form_fields(spec.form_fields)

    try:
        validate_form_schema(metadata_json)
    except BadRequestException as exc:
        result.add_error(
            step_ref=None,
            code="form_schema_invalid",
            message=str(exc),
        )

    try:
        validate_variable_alias_collisions_for_step_graph(
            steps=flow_steps,
            metadata_json=metadata_json,
        )
    except FlowStepValidationError as exc:
        result.add_error(
            step_ref=_step_ref_from_order(spec, exc.step_order),
            code="variable_alias_collision",
            message=str(exc),
        )
    except BadRequestException as exc:
        result.add_error(
            step_ref=None,
            code="variable_alias_collision",
            message=str(exc),
        )

    for issue in collect_step_graph_issues(
        flow_steps,
        metadata_json=metadata_json,
        require_complete_template_fill_config=False,
    ):
        if _builder_ignores_graph_issue(issue):
            continue
        result.add_error(
            step_ref=_step_ref_from_order(spec, issue.step_order)
            if issue.step_order is not None
            else None,
            code=_builder_code_from_graph_issue(issue),
            message=_builder_message_from_graph_issue(issue),
        )


def _step_ref_from_order(spec: FlowDraftSpecCore, step_order: int) -> str | None:
    if step_order < 1 or step_order > len(spec.steps):
        return None
    return spec.steps[step_order - 1].plan_step_ref


def _builder_ignores_graph_issue(issue: FlowStepGraphIssue) -> bool:
    return (
        issue.code in _BUILDER_IGNORED_FLOW_VALIDATION_CODES
        or issue.exception_code in _BUILDER_IGNORED_FLOW_VALIDATION_EXCEPTION_CODES
    )


def _builder_code_from_graph_issue(issue: FlowStepGraphIssue) -> str:
    mapped = _CANONICAL_GRAPH_CODE_TO_BUILDER_CODE.get(issue.code)
    if mapped is not None:
        return mapped
    if issue.code in _CANONICAL_GRAPH_CODES_WITH_GENERIC_BUILDER_PRESENTATION:
        return "flow_step_invalid"
    return "flow_step_invalid"


def _builder_message_from_graph_issue(issue: FlowStepGraphIssue) -> str:
    if issue.code == FlowGraphIssueCode.DUPLICATE_STEP_NAME:
        return f"Duplicate step name. {issue.message}"
    return issue.message
