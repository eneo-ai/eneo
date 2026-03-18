from __future__ import annotations

from typing import Any
from uuid import uuid4

from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore, FormFieldSpec
from intric.flows.ai_builder.ai_builder_reference_rewriter import (
    build_ref_to_order,
    rewrite_step_spec_variables,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.flow import FlowStep
from intric.flows.flow_validators import (
    validate_form_schema,
    validate_steps,
    validate_variable_alias_collisions,
)
from intric.main.exceptions import BadRequestException


def validate_flow_service_parity(spec: FlowDraftSpecCore, result: SpecValidationResult) -> None:
    """Run the same production validators used by FlowService where possible."""
    flow_steps = _spec_to_flow_steps(spec)
    metadata_json = _metadata_json_from_form_fields(spec.form_fields)

    try:
        validate_form_schema(metadata_json)
    except BadRequestException as exc:
        result.add_error(
            step_ref=None,
            code="form_schema_invalid",
            message=str(exc),
        )

    try:
        validate_variable_alias_collisions(steps=flow_steps, metadata_json=metadata_json)
    except BadRequestException as exc:
        result.add_error(
            step_ref=None,
            code="variable_alias_collision",
            message=str(exc),
        )

    try:
        validate_steps(
            flow_steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=False,
        )
    except BadRequestException as exc:
        if _is_builder_unsupported_audio_transcription_error(str(exc)):
            return
        result.add_error(
            step_ref=_infer_step_ref_from_message(spec, str(exc)),
            code="flow_step_invalid",
            message=str(exc),
        )


def _spec_to_flow_steps(spec: FlowDraftSpecCore) -> list[FlowStep]:
    ref_to_order = build_ref_to_order(spec.steps)
    return [
        FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=index + 1,
            user_description=rewritten_step.name,
            input_source=rewritten_step.input_source.value,
            input_type=rewritten_step.input_type.value,
            output_mode=rewritten_step.output_mode.value,
            output_type=rewritten_step.output_type.value,
            mcp_policy=rewritten_step.mcp_policy.value,
            input_bindings=rewritten_step.input_bindings,
            input_contract=rewritten_step.input_contract,
            output_contract=rewritten_step.output_contract,
            input_config=rewritten_step.input_config,
            output_config=rewritten_step.output_config,
        )
        for index, rewritten_step in enumerate(
            [rewrite_step_spec_variables(step, ref_to_order) for step in spec.steps]
        )
    ]


def _metadata_json_from_form_fields(
    form_fields: list[FormFieldSpec] | None,
) -> dict[str, Any] | None:
    if form_fields is None:
        return None
    return {
        "form_schema": {
            "fields": [
                {
                    "name": field.name,
                    "type": field.type,
                    "label": field.label,
                    "required": field.required,
                    **({"options": field.options} if field.options is not None else {}),
                }
                for field in form_fields
            ]
        }
    }


def _infer_step_ref_from_message(spec: FlowDraftSpecCore, message: str) -> str | None:
    for index, step in enumerate(spec.steps, start=1):
        if f"Step {index}:" in message:
            return step.plan_step_ref
    return None


def _is_builder_unsupported_audio_transcription_error(message: str) -> bool:
    return (
        "Transcription must be enabled when using audio input steps." in message
        or "A transcription model must be selected when using audio input steps." in message
    )
