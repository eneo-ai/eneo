from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.enums import FlowOutputMode, FlowOutputType
from intric.flows.flow import FlowStep
from intric.flows.flow_review_policy import (
    FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED,
    FlowStepReviewMode,
    FlowStepReviewPolicy,
)
from intric.flows.flow_validators import validate_form_schema, validate_steps
from intric.flows.flow_validators_form import (
    normalize_legacy_form_schema,
    validate_variable_alias_collisions,
)
from intric.main.exceptions import BadRequestException


def _step(step_order: int = 1, **updates) -> FlowStep:
    step = FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
        mcp_policy="inherit",
    )
    return step.model_copy(update=updates)


def test_validate_steps_rejects_unsupported_enum_values():
    with pytest.raises(BadRequestException, match="unsupported input_type 'banana'"):
        validate_steps([_step(input_type="banana")])


def test_validate_steps_rejects_output_contract_for_text_output():
    with pytest.raises(
        BadRequestException,
        match="output_contract is not supported for output_type 'text'",
    ):
        validate_steps(
            [
                _step(
                    output_type="text",
                    output_contract={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    },
                )
            ]
        )


def test_validate_steps_rejects_http_get_body_fields():
    with pytest.raises(
        BadRequestException,
        match="body fields are only allowed for input_source 'http_post'",
    ):
        validate_steps(
            [
                _step(
                    input_source="http_get",
                    input_config={"url": "https://example.com", "body_json": {"x": 1}},
                )
            ]
        )


def test_validate_steps_rejects_file_like_input_types_for_http_sources():
    with pytest.raises(
        BadRequestException,
        match="input_type 'image' is not supported with input_source 'http_get'",
    ):
        validate_steps(
            [
                _step(
                    input_source="http_get",
                    input_type="image",
                    input_config={"url": "https://example.com"},
                )
            ]
        )


def test_validate_form_schema_options_error_mentions_select_and_multiselect():
    with pytest.raises(
        BadRequestException, match="only valid for select or multiselect"
    ):
        validate_form_schema(
            {
                "form_schema": {
                    "fields": [
                        {"name": "Age", "type": "number", "options": ["bad"]},
                    ]
                }
            }
        )


def test_validate_steps_rejects_http_body_template_and_body_json_together():
    with pytest.raises(
        BadRequestException, match="cannot define both body_template and body_json"
    ):
        validate_steps(
            [
                _step(
                    input_source="http_post",
                    input_config={
                        "url": "https://example.com",
                        "body_template": "{{flow_input.text}}",
                        "body_json": {"x": 1},
                    },
                )
            ]
        )


def test_validate_steps_rejects_invalid_http_response_format():
    with pytest.raises(
        BadRequestException, match="response_format must be 'text' or 'json'"
    ):
        validate_steps(
            [
                _step(
                    input_source="http_post",
                    input_config={
                        "url": "https://example.com",
                        "response_format": "xml",
                    },
                )
            ]
        )


def test_validate_steps_rejects_forward_binding_reference_directly():
    with pytest.raises(
        BadRequestException, match="only reference outputs from earlier steps"
    ):
        validate_steps(
            [
                _step(1, input_bindings={"value": "{{step_2.output.text}}"}),
                _step(2),
            ]
        )


def test_validate_steps_allows_runtime_step_input_reference_in_bindings():
    validate_steps(
        [
            _step(
                input_type="document",
                input_config={
                    "runtime_input": {"enabled": True, "input_format": "document"}
                },
                input_bindings={"value": "{{step_input.text}}"},
            )
        ]
    )


def test_validate_form_schema_rejects_duplicate_field_names_case_insensitive():
    with pytest.raises(BadRequestException, match="name must be unique"):
        validate_form_schema(
            {
                "form_schema": {
                    "fields": [
                        {"name": "CaseId", "type": "text"},
                        {"name": "caseid", "type": "text"},
                    ]
                }
            }
        )


def test_validate_steps_rejects_template_fill_for_non_docx_output():
    with pytest.raises(
        BadRequestException, match="template_fill requires output_type 'docx'"
    ):
        validate_steps(
            [
                _step(
                    output_mode="template_fill",
                    output_type="pdf",
                    output_config={
                        "template_file_id": str(uuid4()),
                        "bindings": {"section": "{{step_1.output.text}}"},
                    },
                )
            ]
        )


def test_validate_steps_allows_incomplete_template_fill_config_while_editing():
    validate_steps(
        [
            _step(
                output_mode="template_fill",
                output_type="docx",
                output_config={"bindings": {}},
            )
        ]
    )


def test_validate_steps_rejects_template_fill_binding_to_future_step():
    with pytest.raises(BadRequestException, match="earlier steps"):
        validate_steps(
            [
                _step(
                    step_order=1,
                    output_mode="template_fill",
                    output_type="docx",
                    output_config={
                        "template_file_id": str(uuid4()),
                        "bindings": {"section": "{{step_2.output.text}}"},
                    },
                ),
                _step(step_order=2),
            ]
        )


def test_validate_steps_allows_explicit_empty_template_bindings_for_publish():
    validate_steps(
        [
            _step(
                output_mode="template_fill",
                output_type="docx",
                output_config={
                    "template_file_id": str(uuid4()),
                    "bindings": {"optional_section": ""},
                },
            )
        ],
        require_complete_template_fill_config=True,
    )


def test_validate_steps_rejects_inline_citation_mode_for_non_text_output() -> None:
    with pytest.raises(
        BadRequestException,
        match="citation_mode 'inline_inref_sidecar' requires output_type 'text'",
    ):
        validate_steps(
            [
                _step(
                    output_type="json",
                    output_config={"citation_mode": "inline_inref_sidecar"},
                )
            ]
        )


def test_validate_steps_rejects_inline_citation_mode_for_transcribe_only_output() -> (
    None
):
    with pytest.raises(
        BadRequestException,
        match="citation_mode 'inline_inref_sidecar' requires an LLM-backed text step",
    ):
        validate_steps(
            [
                _step(
                    input_type="audio",
                    output_type="text",
                    output_mode="transcribe_only",
                    output_config={"citation_mode": "inline_inref_sidecar"},
                )
            ]
        )


def test_validate_steps_allows_inline_citation_mode_for_text_llm_steps() -> None:
    # Passing enum members here so `model_copy(update=...)` preserves enum
    # identity — production `FlowStep` objects carry `FlowOutputType` /
    # `FlowOutputMode` instances after Pydantic validation, and the FCM's
    # `is_citation_capable_step` uses `is` identity comparisons that
    # would silently fail on raw strings.
    validate_steps(
        [
            _step(
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
                output_config={"citation_mode": "inline_inref_sidecar"},
            )
        ]
    )


def test_validate_steps_allows_review_policy_on_in_process_output() -> None:
    validate_steps(
        [
            _step(
                review_policy=FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT),
            )
        ]
    )


def test_validate_steps_rejects_review_policy_for_http_post_output() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        validate_steps(
            [
                _step(
                    output_mode=FlowOutputMode.HTTP_POST,
                    output_config={"url": "https://example.test/review"},
                    review_policy={"mode": "view"},
                )
            ]
        )

    assert exc_info.value.code == FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED


def test_normalize_legacy_form_schema_maps_legacy_string_type_to_text():
    metadata_json = {
        "form_schema": {
            "fields": [
                {"name": "CustomerName", "type": "string"},
                {"name": "Category", "type": "select"},
            ]
        }
    }

    normalized = normalize_legacy_form_schema(metadata_json)

    assert normalized == {
        "form_schema": {
            "fields": [
                {"name": "CustomerName", "type": "text"},
                {"name": "Category", "type": "select"},
            ]
        }
    }


def test_validate_variable_alias_collisions_rejects_step_name_matching_form_field():
    with pytest.raises(BadRequestException, match="conflicts with form field name"):
        validate_variable_alias_collisions(
            steps=[_step(user_description="CaseId")],
            metadata_json={
                "form_schema": {
                    "fields": [
                        {"name": "caseid", "type": "text"},
                    ]
                }
            },
        )
