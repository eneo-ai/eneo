from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.flow import FlowStep
from intric.flows.flow_validators import validate_form_schema, validate_steps
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
    with pytest.raises(BadRequestException, match="output_contract is not supported for output_type 'text'"):
        validate_steps(
            [
                _step(
                    output_type="text",
                    output_contract={"type": "object", "properties": {"value": {"type": "string"}}},
                )
            ]
        )


def test_validate_steps_rejects_http_get_body_fields():
    with pytest.raises(BadRequestException, match="body fields are only allowed for input_source 'http_post'"):
        validate_steps(
            [
                _step(
                    input_source="http_get",
                    input_config={"url": "https://example.com", "body_json": {"x": 1}},
                )
            ]
        )


def test_validate_steps_rejects_file_like_input_types_for_http_sources():
    with pytest.raises(BadRequestException, match="input_type 'image' is not supported with input_source 'http_get'"):
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
    with pytest.raises(BadRequestException, match="only valid for select or multiselect"):
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
    with pytest.raises(BadRequestException, match="cannot define both body_template and body_json"):
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
    with pytest.raises(BadRequestException, match="response_format must be 'text' or 'json'"):
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
    with pytest.raises(BadRequestException, match="only reference outputs from earlier steps"):
        validate_steps(
            [
                _step(1, input_bindings={"value": "{{step_2.output.text}}"}),
                _step(2),
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
    with pytest.raises(BadRequestException, match="template_fill requires output_type 'docx'"):
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
