"""Validation for AI Builder flow specs."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.ai_builder.ai_builder_validation_quality import (
    lint_all_previous_steps_overuse,
    lint_all_previous_with_specific_refs,
    lint_contract_instruction_alignment,
    lint_json_output_without_contract,
    lint_multi_goal_prompts,
    lint_shadowed_form_field_bare_references,
    lint_single_step_flow,
    lint_source_material_underlag_boundaries,
    lint_unfiltered_structured_interpolation,
    lint_unused_form_fields,
    lint_vague_step_names,
)
from intric.flows.ai_builder.ai_builder_validation_references import (
    validate_variable_references,
)
from intric.flows.domain.flow_step_validation import (
    FlowStepGraphIssue,
    FlowStepValidationError,
)
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    metadata_json_from_authoring_form_fields,
)
from intric.flows.flow_authoring_variable_rewriting import (
    flow_step_validation_views_from_draft_spec,
)
from intric.flows.flow_validators import (
    FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED,
    FLOW_AUDIO_TRANSCRIPTION_REQUIRED,
    collect_step_graph_issues,
    validate_form_schema,
)
from intric.flows.flow_validators_form import (
    validate_variable_alias_collisions_for_step_graph,
)
from intric.main.exceptions import BadRequestException

_BUILDER_IGNORED_FLOW_VALIDATION_CODES = frozenset(
    {
        FLOW_AUDIO_TRANSCRIPTION_MODEL_REQUIRED,
        FLOW_AUDIO_TRANSCRIPTION_REQUIRED,
    }
)
_CANONICAL_GRAPH_CODE_TO_BUILDER_CODE: dict[str, str] = {
    "audio_document_transcript_chain_invalid": (
        "audio_document_transcript_chain_invalid"
    ),
    "duplicate_step_name": "duplicate_step_name",
    "flow_audio_transcription_invalid": "flow_audio_transcription_invalid",
    "flow_http_post_output_must_be_terminal": (
        "flow_http_post_output_must_be_terminal"
    ),
    "flow_input_contract_inapplicable": "input_contract_type_mismatch",
    "typed_io_invalid_input_source_position": "first_step_invalid_source",
    "typed_io_multiple_flow_input_steps": "multiple_flow_input",
    "typed_io_flow_input_position_invalid": "flow_input_not_first",
    "typed_io_document_source_unsupported": "media_source_mismatch",
    "typed_io_audio_source_unsupported": "media_source_mismatch",
    "typed_io_file_source_unsupported": "media_source_mismatch",
    "typed_io_invalid_input_source_combination": "json_all_previous_incompatible",
    "typed_io_incompatible_type_chain": "incompatible_type_chain",
    "transcribe_only_violation": "transcribe_only_violation",
    "template_fill_requires_docx": "template_fill_requires_docx",
    "invalid_input_contract_schema": "invalid_input_contract_schema",
    "invalid_output_contract_schema": "invalid_output_contract_schema",
    "input_contract_type_mismatch": "input_contract_type_mismatch",
    "input_contract_source_mismatch": "input_contract_type_mismatch",
    "output_contract_type_mismatch": "output_contract_type_mismatch",
    "output_contract_template_fill_incompatible": (
        "output_contract_template_fill_incompatible"
    ),
    "unsupported_input_type": "unsupported_input_type",
}
_CANONICAL_GRAPH_CODES_WITH_GENERIC_BUILDER_PRESENTATION = frozenset(
    {
        "duplicate_step_order",
        "flow_input_binding_unsupported_key",
        "flow_review_policy_invalid",
        "flow_step_invalid",
        "step_order_not_contiguous",
        "typed_io_missing_previous_step",
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
        lint_source_material_underlag_boundaries(spec, result)

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
        or issue.exception_code in _BUILDER_IGNORED_FLOW_VALIDATION_CODES
    )


def _builder_code_from_graph_issue(issue: FlowStepGraphIssue) -> str:
    mapped = _CANONICAL_GRAPH_CODE_TO_BUILDER_CODE.get(issue.code)
    if mapped is not None:
        return mapped
    if issue.code in _CANONICAL_GRAPH_CODES_WITH_GENERIC_BUILDER_PRESENTATION:
        return "flow_step_invalid"
    return "flow_step_invalid"


def _builder_message_from_graph_issue(issue: FlowStepGraphIssue) -> str:
    if issue.code == "duplicate_step_name":
        return f"Duplicate step name. {issue.message}"
    return issue.message
