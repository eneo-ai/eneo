from __future__ import annotations

from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    OutputType,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    canonicalize_flow_spec_resources,
    format_resource_resolution_feedback,
)
from intric.flows.ai_builder.ai_builder_session_spec_validator import (
    normalize_compiled_spec_for_session,
    validate_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.main.logging import get_logger

logger = get_logger(__name__)
_STRICT_TERMINAL_OUTPUT_TYPES = frozenset(
    {OutputType.JSON, OutputType.PDF, OutputType.DOCX}
)


@dataclass(frozen=True)
class PreparedCompiledSpecResult:
    spec: FlowDraftSpecCore | None
    validation: SpecValidationResult | None
    failure_feedback: str | None = None


def prepare_compiled_spec_for_session(
    *,
    spec: FlowDraftSpecCore,
    target_kind: TargetKind,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None,
    valid_existing_step_refs: list[str] | None,
    terminal_output_type: OutputType | None = None,
) -> PreparedCompiledSpecResult:
    prepared_spec = normalize_compiled_spec_for_session(
        spec,
        target_kind=target_kind,
    )
    prepared_spec, normalization_changes = normalize_ai_builder_spec(
        prepared_spec,
        terminal_output_type=terminal_output_type,
    )
    artifact_tail_changes = [
        {
            "step_ref": step.plan_step_ref,
            "code": change.code,
            "field": change.field_suffix,
        }
        for step, change in normalization_changes
        if change.code == "terminal_artifact_helper_folded"
    ]
    if artifact_tail_changes:
        logger.info(
            "ai_builder_terminal_artifact_tail_normalized "
            "target_kind=%s terminal_output_type=%s changes=%s",
            target_kind,
            terminal_output_type,
            artifact_tail_changes,
        )
    if resource_catalog is not None:
        prepared_spec, resolution_issues = canonicalize_flow_spec_resources(
            prepared_spec,
            catalog=resource_catalog,
        )
        if resolution_issues:
            return PreparedCompiledSpecResult(
                spec=None,
                validation=None,
                failure_feedback=format_resource_resolution_feedback(resolution_issues),
            )

    validation = validate_spec(
        prepared_spec,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
    )
    session_validation = validate_compiled_spec_for_session(
        prepared_spec,
        target_kind=target_kind,
        valid_existing_step_refs=valid_existing_step_refs,
    )
    for error in session_validation.errors:
        validation.add_error(
            step_ref=error.step_ref,
            code=error.code,
            message=error.message,
        )
    _add_terminal_output_alignment_error(
        validation=validation,
        spec=prepared_spec,
        terminal_output_type=terminal_output_type,
    )

    return PreparedCompiledSpecResult(
        spec=prepared_spec,
        validation=validation,
    )


def _add_terminal_output_alignment_error(
    *,
    validation: SpecValidationResult,
    spec: FlowDraftSpecCore,
    terminal_output_type: OutputType | None,
) -> None:
    if (
        terminal_output_type is None
        or terminal_output_type not in _STRICT_TERMINAL_OUTPUT_TYPES
        or not spec.steps
    ):
        return

    terminal_step = spec.steps[-1]
    if terminal_step.output_type == terminal_output_type:
        return

    validation.add_error(
        step_ref=terminal_step.plan_step_ref,
        code="terminal_output_type_mismatch",
        message=(
            "The final step output_type must match the requested terminal output "
            f"'{terminal_output_type.value}', but the compiled plan ends with "
            f"'{terminal_step.output_type.value}'. Update the final step instead of "
            "adding or preserving a trailing text step."
        ),
    )
