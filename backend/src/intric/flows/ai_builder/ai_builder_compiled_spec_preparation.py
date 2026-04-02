from __future__ import annotations

from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore, TargetKind
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
) -> PreparedCompiledSpecResult:
    prepared_spec = normalize_compiled_spec_for_session(
        spec,
        target_kind=target_kind,
    )
    prepared_spec, _ = normalize_ai_builder_spec(prepared_spec)
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

    return PreparedCompiledSpecResult(
        spec=prepared_spec,
        validation=validation,
    )
