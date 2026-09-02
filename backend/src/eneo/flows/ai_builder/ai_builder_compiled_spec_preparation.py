from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    canonicalize_flow_spec_resources,
    format_resource_resolution_feedback,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    disambiguate_ai_builder_step_names,
    normalize_ai_builder_spec,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputType,
)

_STRICT_EDIT_TERMINAL_OUTPUT_TYPES = frozenset(
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
    terminal_output_type: OutputType | None = None,
    ui_language: str | None = None,
) -> PreparedCompiledSpecResult:
    prepared_spec = spec
    if target_kind == TargetKind.EDIT:
        prepared_spec, _normalization_changes = normalize_ai_builder_spec(
            spec,
            terminal_output_type=terminal_output_type,
            disambiguate_duplicate_step_names=True,
            ui_language=ui_language,
        )
    else:
        prepared_spec, _normalization_changes = disambiguate_ai_builder_step_names(spec)
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
    _enforce_terminal_output_alignment(
        validation=validation,
        spec=prepared_spec,
        terminal_output_type=terminal_output_type,
        target_kind=target_kind,
    )
    return PreparedCompiledSpecResult(spec=prepared_spec, validation=validation)


def _enforce_terminal_output_alignment(
    *,
    validation: SpecValidationResult,
    spec: FlowDraftSpecCore,
    terminal_output_type: OutputType | None,
    target_kind: TargetKind,
) -> None:
    if (
        terminal_output_type is None
        or not spec.steps
        or (
            target_kind == TargetKind.EDIT
            and terminal_output_type not in _STRICT_EDIT_TERMINAL_OUTPUT_TYPES
        )
    ):
        return

    terminal_step = spec.steps[-1]
    if terminal_step.output_type == terminal_output_type:
        return

    if target_kind == TargetKind.CREATE:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            repair_disposition="server_defect",
            detail=(
                "The create compiler produced a terminal output type that does "
                "not match the committed architecture."
            ),
            log_context={
                "failure_code": "terminal_output_type_mismatch",
                "reason": "terminal_output_type_mismatch",
                "expected_output_type": terminal_output_type.value,
                "actual_output_type": terminal_step.output_type.value,
                "step_ref": terminal_step.plan_step_ref,
            },
        )

    message = (
        "The final step output_type must match the requested terminal output "
        f"'{terminal_output_type.value}', but the compiled plan ends with "
        f"'{terminal_step.output_type.value}'. Update the final step instead of "
        "adding or preserving a trailing text step."
    )
    validation.add_error(
        step_ref=terminal_step.plan_step_ref,
        code="terminal_output_type_mismatch",
        message=message,
    )
