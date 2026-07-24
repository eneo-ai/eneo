from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
    flow_step_validation_views_from_flow_steps,
)
from eneo.flows.enums import FlowOutputMode, FlowOutputType
from eneo.flows.flow_metadata import normalize_flow_metadata_for_write
from eneo.flows.flow_review_policy import (
    FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED,
    FlowStepReviewMode,
    FlowStepReviewPolicy,
)
from eneo.flows.flow_validators import (
    FLOW_AUDIO_TRANSCRIPTION_REQUIRED,
    collect_step_graph_issues,
    validate_form_schema,
    validate_steps,
)
from eneo.flows.flow_validators_form import validate_variable_alias_collisions
from eneo.main.exceptions import BadRequestException


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
    )
    return step.model_copy(update=updates)


def _audio_metadata() -> dict:
    return {
        "wizard": {
            "transcription_enabled": True,
            "transcription_model": {"id": str(uuid4())},
            "transcription_language": "sv",
        }
    }


def _form_metadata(*field_names: str) -> dict:
    return {
        "form_schema": {
            "fields": [
                {"name": field_name, "type": "text"} for field_name in field_names
            ]
        }
    }


def _assert_validate_steps_rejects(
    steps: list[FlowStep],
    *,
    expected_type: type[BadRequestException],
    match: str,
    code: str | None = None,
    step_order: int | None = None,
    metadata_json: dict | None = None,
    require_complete_template_fill_config: bool = False,
) -> BadRequestException:
    with pytest.raises(BadRequestException, match=match) as exc_info:
        validate_steps(
            steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=require_complete_template_fill_config,
        )

    exc = exc_info.value
    assert type(exc) is expected_type
    assert exc.code == code
    if step_order is not None:
        assert isinstance(exc, FlowStepValidationError)
        assert exc.step_order == step_order
    return exc


def test_validate_steps_rejects_unsupported_enum_values():
    with pytest.raises(BadRequestException, match="unsupported input_type 'banana'"):
        validate_steps([_step(input_type="banana")])


@pytest.mark.parametrize(
    "raw_policy",
    [
        None,
        {},
        {"version": "1", "mode": "fail_closed"},
        {"version": True, "mode": "fail_closed"},
        {"version": 2, "mode": "fail_closed"},
        {"version": 1, "mode": "unknown"},
        {"version": 1, "mode": "fail_closed", "unexpected": True},
    ],
)
def test_validate_steps_rejects_invalid_retrieval_policy(raw_policy: object) -> None:
    _assert_validate_steps_rejects(
        [_step(output_config={"retrieval_policy": raw_policy})],
        expected_type=FlowStepValidationError,
        match="retrieval_policy is invalid",
        step_order=1,
    )


@pytest.mark.parametrize("output_mode", ["pass_through", "http_post"])
def test_validate_steps_accepts_retrieval_policy_for_retrieval_completion_modes(
    output_mode: str,
) -> None:
    output_config: dict[str, object] = {
        "retrieval_policy": {"version": 1, "mode": "fail_closed"}
    }
    if output_mode == "http_post":
        output_config.update(
            {
                "url": "https://example.test/hook",
                "auth": {"mode": "none"},
            }
        )
    validate_steps([_step(output_mode=output_mode, output_config=output_config)])


@pytest.mark.parametrize(
    "output_mode",
    ["compose_text", "transcribe_only", "template_fill", "render_verbatim"],
)
def test_validate_steps_rejects_retrieval_policy_for_non_retrieval_mode(
    output_mode: str,
) -> None:
    output_config: dict[str, object] = {
        "retrieval_policy": {"version": 1, "mode": "fail_closed"}
    }
    output_type = "json"
    if output_mode == "template_fill":
        output_config.update(
            {
                "bindings": {},
                "template_asset_id": str(uuid4()),
            }
        )
        output_type = "docx"
    _assert_validate_steps_rejects(
        [
            _step(
                output_mode=output_mode,
                output_type=output_type,
                output_config=output_config,
            )
        ],
        expected_type=FlowStepValidationError,
        match="supported only for retrieval-plus-completion output modes",
        step_order=1,
    )


def test_validate_steps_fail_fast_rejects_duplicate_step_order() -> None:
    _assert_validate_steps_rejects(
        [_step(1), _step(1)],
        expected_type=BadRequestException,
        match="Duplicate step_order detected.",
    )


def test_validate_steps_fail_fast_rejects_non_contiguous_step_order() -> None:
    _assert_validate_steps_rejects(
        [_step(1), _step(3)],
        expected_type=BadRequestException,
        match="Step order must be contiguous and start at 1.",
    )


def test_validate_steps_fail_fast_rejects_duplicate_step_names() -> None:
    _assert_validate_steps_rejects(
        [
            _step(1, user_description="Summarize"),
            _step(2, user_description=" summarize "),
        ],
        expected_type=BadRequestException,
        match="Step names must be unique",
    )


def test_validate_steps_fail_fast_prefers_duplicate_name_before_chain_violation() -> (
    None
):
    _assert_validate_steps_rejects(
        [
            _step(1, user_description="Same"),
            _step(
                2,
                user_description=" same ",
                input_source="all_previous_steps",
                input_type="json",
            ),
        ],
        expected_type=BadRequestException,
        match="Step names must be unique",
    )


@pytest.mark.parametrize(
    ("steps", "match", "step_order"),
    [
        (
            [_step(1, input_source="previous_step")],
            "Step 1 cannot use previous_step/all_previous_steps",
            1,
        ),
        (
            [_step(1), _step(2, input_source="flow_input")],
            "Only one step may use input_source 'flow_input'.",
            2,
        ),
        (
            [
                _step(1, input_source="previous_step"),
                _step(2, input_source="flow_input"),
            ],
            "input_source 'flow_input' must be step 1 if present.",
            2,
        ),
        (
            [_step(1), _step(2, input_source="previous_step", input_type="document")],
            "input_type 'document' is only supported with input_source 'flow_input'",
            2,
        ),
        (
            [_step(1), _step(2, input_source="all_previous_steps", input_type="json")],
            "input_type 'json' is incompatible with input_source 'all_previous_steps'",
            2,
        ),
        (
            [_step(1, output_type="docx"), _step(2, input_type="json")],
            "incompatible type chain",
            2,
        ),
    ],
)
def test_validate_steps_fail_fast_preserves_first_chain_violation(
    steps: list[FlowStep], match: str, step_order: int
) -> None:
    _assert_validate_steps_rejects(
        steps,
        expected_type=FlowStepValidationError,
        match=match,
        step_order=step_order,
    )


def test_validate_steps_fail_fast_prefers_global_chain_violation_before_type_pair() -> (
    None
):
    _assert_validate_steps_rejects(
        [
            _step(1, output_type="docx"),
            _step(2, input_source="flow_input", output_type="docx"),
            _step(3, input_source="previous_step", input_type="json"),
        ],
        expected_type=FlowStepValidationError,
        match="Only one step may use input_source 'flow_input'.",
        step_order=2,
    )


@pytest.mark.parametrize(
    ("step", "match"),
    [
        (
            _step(output_mode="transcribe_only", input_type="text", output_type="text"),
            "output_mode 'transcribe_only' requires input_type 'audio'",
        ),
        (
            _step(
                output_mode="transcribe_only", input_type="audio", output_type="docx"
            ),
            "output_mode 'transcribe_only' requires output_type 'text'",
        ),
        (
            _step(
                output_mode="template_fill",
                output_type="pdf",
                output_config={"template_asset_id": str(uuid4()), "bindings": {}},
            ),
            "template_fill requires output_type 'docx'",
        ),
        (
            _step(output_mode="pass_through", input_type="text", output_type="pdf"),
            "output_mode 'pass_through' is not supported for text-to-pdf document steps",
        ),
        (
            _step(output_mode="pass_through", input_type="text", output_type="docx"),
            "output_mode 'pass_through' is not supported for text-to-docx document steps",
        ),
    ],
)
def test_validate_steps_fail_fast_preserves_output_mode_validation(
    step: FlowStep, match: str
) -> None:
    _assert_validate_steps_rejects(
        [step],
        expected_type=FlowStepValidationError,
        match=match,
        step_order=1,
    )


@pytest.mark.parametrize(
    ("step", "match"),
    [
        (
            _step(input_contract={"type": "not-a-json-schema-type"}),
            "input_contract is not a valid JSON Schema",
        ),
        (
            _step(output_contract={"type": "not-a-json-schema-type"}),
            "output_contract is not a valid JSON Schema",
        ),
        (
            _step(
                input_type="document",
                input_contract={"type": "object", "properties": {}},
            ),
            "input_contract is not supported for input_type 'document'",
        ),
        (
            _step(
                output_type="text",
                output_contract={"type": "object", "properties": {}},
            ),
            "output_contract is not supported for output_type 'text'",
        ),
        (
            _step(
                output_mode="template_fill",
                output_type="docx",
                output_contract={"type": "object", "properties": {}},
            ),
            "output_contract is not supported for output_mode 'template_fill'",
        ),
        (
            _step(
                1,
                input_type="json",
                output_type="pdf",
                output_contract={"type": "not-a-json-schema-type"},
            ),
            "output_contract is not a valid JSON Schema",
        ),
    ],
)
def test_validate_steps_fail_fast_preserves_contract_validation(
    step: FlowStep, match: str
) -> None:
    _assert_validate_steps_rejects(
        [step],
        expected_type=FlowStepValidationError,
        match=match,
        step_order=1,
    )


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


def test_validate_steps_rejects_authored_http_get_body_fields():
    with pytest.raises(
        BadRequestException,
        match="HTTP_BODY_NOT_ALLOWED_FOR_GET",
    ):
        validate_steps(
            [
                _step(
                    input_source="http_get",
                    input_config={
                        "url": "https://example.com",
                        "auth": {"mode": "none"},
                        "body": {"mode": "json_template", "template": '{"x": 1}'},
                    },
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


def test_validate_steps_rejects_legacy_http_post_input_source():
    with pytest.raises(
        BadRequestException, match="unsupported input_source 'http_post'"
    ):
        validate_steps(
            [
                _step(
                    input_source="http_post",
                    input_config={
                        "url": "https://example.com",
                        "auth": {"mode": "none"},
                    },
                )
            ]
        )


def test_validate_steps_rejects_invalid_http_response_format():
    with pytest.raises(BadRequestException, match="response_format"):
        validate_steps(
            [
                _step(
                    input_source="http_get",
                    input_config={
                        "url": "https://example.com",
                        "auth": {"mode": "none"},
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
                _step(1, input_bindings={"question": "{{step_2.output.text}}"}),
                _step(2),
            ]
        )


@pytest.mark.parametrize(
    "question",
    [
        "{{ case_id }}",
        "{{ flow_input.case_id }}",
        "{{ flow_input }}",
        "{{ flow_input.text }}",
        "{{ datum }}",
        "{{ indata_text }}",
        "{{ transkribering }}",
        "{{ flow_input.datum }}",
        "{{ flow_input.indata_text }}",
    ],
)
def test_validate_steps_publish_accepts_declared_and_runtime_input_names(
    question: str,
) -> None:
    validate_steps(
        [_step(input_bindings={"question": question})],
        metadata_json=_form_metadata("case_id", "datum", "indata_text"),
        require_complete_template_fill_config=True,
    )


@pytest.mark.parametrize(
    ("question", "code", "context"),
    [
        (
            "{{ undeclared }}",
            "flow_input_binding_invalid_step_reference",
            {
                "field": "input_bindings.question",
                "reference": "undeclared",
            },
        ),
        (
            "{{ flow_input.undeclared }}",
            "flow_input_binding_unsupported_key",
            {
                "field": "input_bindings.question",
                "key": "flow_input.undeclared",
            },
        ),
        (
            "{{ datum.year }}",
            "flow_input_binding_unsupported_key",
            {
                "field": "input_bindings.question",
                "key": "datum.year",
            },
        ),
    ],
)
def test_validate_steps_publish_rejects_unknown_input_names_with_precise_context(
    question: str,
    code: str,
    context: dict[str, str],
) -> None:
    exc = _assert_validate_steps_rejects(
        [_step(input_bindings={"question": question})],
        expected_type=FlowStepValidationError,
        match=question.strip("{} "),
        code=code,
        step_order=1,
        metadata_json=_form_metadata("case_id"),
        require_complete_template_fill_config=True,
    )

    assert exc.context == context


def test_validate_steps_projects_publish_binding_error_to_exact_issue() -> None:
    steps = [_step(input_bindings={"question": "{{ undeclared }}"})]

    issues = collect_step_graph_issues(
        flow_step_validation_views_from_flow_steps(steps),
        metadata_json=_form_metadata("case_id"),
        require_complete_template_fill_config=True,
    )

    issue = next(issue for issue in issues if issue.step_order == 1)
    assert issue.code is FlowGraphIssueCode.FLOW_INPUT_BINDING_INVALID_STEP_REFERENCE
    assert issue.exception_code == "flow_input_binding_invalid_step_reference"
    assert issue.context == {
        "field": "input_bindings.question",
        "reference": "undeclared",
    }


@pytest.mark.parametrize(
    "question",
    ["{{ undeclared }}", "{{ flow_input.undeclared }}", "{{ datum.year }}"],
)
def test_validate_steps_draft_preserves_non_numeric_binding_acceptance(
    question: str,
) -> None:
    validate_steps(
        [_step(input_bindings={"question": question})],
        metadata_json=_form_metadata("case_id"),
        require_complete_template_fill_config=False,
    )


@pytest.mark.parametrize(
    "question",
    [
        "{{ step_1 }}",
        "{{ step_1.output }}",
        "{{ step_1.output.text }}",
        "{{ Collect intake }}",
    ],
)
def test_validate_steps_publish_accepts_prior_numeric_and_label_questions(
    question: str,
) -> None:
    validate_steps(
        [
            _step(1, user_description="Collect intake"),
            _step(
                2,
                user_description="Summarize",
                input_bindings={"question": question},
            ),
        ],
        require_complete_template_fill_config=True,
    )


@pytest.mark.parametrize(
    ("question", "current_step_order", "code"),
    [
        (
            "{{ step_bad.output.text }}",
            2,
            "flow_input_binding_invalid_step_reference",
        ),
        (
            "{{ step_2.output.text }}",
            2,
            "flow_input_binding_future_step_reference",
        ),
        (
            "{{ step_3.output.text }}",
            2,
            "flow_input_binding_future_step_reference",
        ),
        (
            "{{ step_0.output.text }}",
            2,
            "flow_input_binding_unknown_step_order",
        ),
        (
            "{{ Summarize }}",
            2,
            "flow_input_binding_future_step_reference",
        ),
        (
            "{{ Deliver }}",
            2,
            "flow_input_binding_future_step_reference",
        ),
        (
            "{{ Unknown label }}",
            2,
            "flow_input_binding_invalid_step_reference",
        ),
        (
            "{{ Collect intake.output.text }}",
            2,
            "flow_input_binding_invalid_step_reference",
        ),
        (
            "{{ collect_input }}",
            2,
            "flow_input_binding_invalid_step_reference",
        ),
        (
            "{{ existing_step_1 }}",
            2,
            "flow_input_binding_invalid_step_reference",
        ),
    ],
)
def test_validate_steps_publish_rejects_invalid_numeric_label_and_authored_questions(
    question: str,
    current_step_order: int,
    code: str,
) -> None:
    steps = [
        _step(1, user_description="Collect intake"),
        _step(2, user_description="Summarize"),
        _step(3, user_description="Deliver"),
    ]
    steps[current_step_order - 1] = steps[current_step_order - 1].model_copy(
        update={"input_bindings": {"question": question}}
    )

    exc = _assert_validate_steps_rejects(
        steps,
        expected_type=FlowStepValidationError,
        match=question.strip("{} "),
        code=code,
        step_order=current_step_order,
        require_complete_template_fill_config=True,
    )

    assert exc.context == {
        "field": "input_bindings.question",
        "reference": question.strip("{} "),
    }


@pytest.mark.parametrize(
    ("question", "code"),
    [
        ("{{ step_bad }}", "flow_input_binding_invalid_step_reference"),
        ("{{ step_2 }}", "flow_input_binding_future_step_reference"),
        ("{{ step_0 }}", "flow_input_binding_unknown_step_order"),
    ],
)
def test_validate_steps_draft_preserves_numeric_reference_rejection(
    question: str,
    code: str,
) -> None:
    _assert_validate_steps_rejects(
        [
            _step(1),
            _step(2, input_bindings={"question": question}),
        ],
        expected_type=FlowStepValidationError,
        match="step",
        code=code,
    )


def test_validate_steps_allows_runtime_step_input_reference_in_bindings():
    validate_steps(
        [
            _step(
                input_type="document",
                input_config={
                    "runtime_input": {"enabled": True, "input_format": "document"}
                },
                input_bindings={"question": "{{step_input.text}}"},
            )
        ]
    )


def test_validate_steps_publish_rejects_unbounded_per_source_runtime_input() -> None:
    _assert_validate_steps_rejects(
        [
            _step(
                input_type="document",
                input_config={
                    "runtime_input": {
                        "enabled": True,
                        "input_format": "document",
                        "execution_mode": "per_source",
                    }
                },
            )
        ],
        expected_type=FlowStepValidationError,
        match="per_source.*max_files",
        step_order=1,
        require_complete_template_fill_config=True,
    )


def test_validate_steps_publish_rejects_unbounded_item_map() -> None:
    _assert_validate_steps_rejects(
        [
            _step(1),
            _step(
                2,
                input_type="json",
                input_config={"item_map": {"enabled": True}},
            ),
        ],
        expected_type=FlowStepValidationError,
        match="item_map.*max_items",
        step_order=2,
        require_complete_template_fill_config=True,
    )


def test_validate_steps_publish_accepts_bounded_mapped_modes() -> None:
    validate_steps(
        [
            _step(
                1,
                input_type="document",
                input_config={
                    "runtime_input": {
                        "enabled": True,
                        "input_format": "document",
                        "execution_mode": "per_source",
                        "max_files": 2,
                    }
                },
            ),
            _step(
                2,
                input_type="json",
                input_config={"item_map": {"enabled": True, "max_items": 2}},
            ),
        ],
        require_complete_template_fill_config=True,
    )


def test_validate_steps_source_refs_do_not_satisfy_runtime_input_consumption() -> None:
    with pytest.raises(
        BadRequestException,
        match="explicit question bindings must reference step_input",
    ):
        validate_steps(
            [
                _step(1),
                _step(
                    2,
                    input_config={
                        "runtime_input": {
                            "enabled": True,
                            "input_format": "document",
                        }
                    },
                    input_bindings={
                        "source_refs": [{"step_ref": "step_1", "output": "text"}]
                    },
                ),
            ]
        )


def test_validate_steps_rejects_unsupported_binding_keys_only_when_publish_strict():
    step = _step(input_bindings={"text": "{{ flow_input.text }}"})

    validate_steps([step], require_complete_template_fill_config=False)

    with pytest.raises(BadRequestException) as exc_info:
        validate_steps([step], require_complete_template_fill_config=True)

    assert exc_info.value.code == "flow_input_binding_unsupported_key"
    assert exc_info.value.context == {
        "field": "input_bindings",
        "key": "text",
    }


def test_validate_steps_rejects_question_binding_with_input_contract():
    with pytest.raises(
        BadRequestException,
        match="input_contract cannot validate input_bindings.question",
    ):
        validate_steps(
            [
                _step(1, output_type="json"),
                _step(
                    2,
                    input_type="text",
                    input_bindings={
                        "question": (
                            "{{ step_1.output.structured }}\n\n"
                            "Källmaterial: {{ step_1.output.text }}"
                        )
                    },
                    input_contract={
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                    },
                ),
            ]
        )


def test_validate_steps_rejects_single_expression_question_binding_with_input_contract():
    with pytest.raises(
        BadRequestException,
        match="input_contract cannot validate input_bindings.question",
    ) as exc_info:
        validate_steps(
            [
                _step(1, output_type="json"),
                _step(
                    2,
                    input_type="json",
                    input_bindings={"question": "{{ step_1.output.structured }}"},
                    input_contract={
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                    },
                ),
            ]
        )

    assert exc_info.value.code == "flow_input_contract_inapplicable"


def test_validate_steps_allows_question_binding_without_input_contract():
    validate_steps(
        [
            _step(1, output_type="json"),
            _step(
                2,
                input_type="json",
                input_bindings={"question": "{{ step_1.output.structured }}"},
            ),
        ]
    )


def _source_sections_contract() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "source_sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section_title": {"type": "string"},
                        "section_body": {"type": "string"},
                        "source_label": {"type": "string"},
                    },
                },
            },
            "report_title": {"type": "string"},
        },
    }


@pytest.mark.parametrize("step_ref", ["step_1", "Collect intake"])
def test_validate_steps_publish_accepts_prior_numeric_and_label_source_refs(
    step_ref: str,
) -> None:
    validate_steps(
        [
            _step(1, user_description="Collect intake"),
            _step(
                2,
                user_description="Summarize",
                input_bindings={
                    "source_refs": [{"step_ref": step_ref, "output": "text"}]
                },
            ),
        ],
        require_complete_template_fill_config=True,
    )


def test_validate_steps_publish_accepts_label_structured_source_ref() -> None:
    validate_steps(
        [
            _step(
                1,
                user_description="Collect intake",
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(
                2,
                user_description="Summarize",
                input_type="text",
                output_type="text",
                output_mode="compose_text",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "Collect intake",
                            "output": "structured",
                            "field_path": "report_title",
                        }
                    ]
                },
            ),
        ],
        require_complete_template_fill_config=True,
    )


@pytest.mark.parametrize(
    ("step_ref", "code"),
    [
        ("step_bad", "flow_input_binding_invalid_step_reference"),
        ("step_2", "flow_input_binding_future_step_reference"),
        ("step_3", "flow_input_binding_future_step_reference"),
        ("step_0", "flow_input_binding_unknown_step_order"),
        ("Summarize", "flow_input_binding_future_step_reference"),
        ("Deliver", "flow_input_binding_future_step_reference"),
        ("Unknown label", "flow_input_binding_invalid_step_reference"),
        ("collect_input", "flow_input_binding_invalid_step_reference"),
        ("existing_step_1", "flow_input_binding_invalid_step_reference"),
    ],
)
def test_validate_steps_publish_rejects_source_refs_with_indexed_context(
    step_ref: str,
    code: str,
) -> None:
    exc = _assert_validate_steps_rejects(
        [
            _step(1, user_description="Collect intake"),
            _step(
                2,
                user_description="Summarize",
                input_bindings={
                    "source_refs": [
                        {"step_ref": "step_1", "output": "text"},
                        {"step_ref": step_ref, "output": "text"},
                    ]
                },
            ),
            _step(3, user_description="Deliver"),
        ],
        expected_type=FlowStepValidationError,
        match=step_ref,
        code=code,
        step_order=2,
        require_complete_template_fill_config=True,
    )

    assert exc.context == {
        "field": "input_bindings.source_refs[1].step_ref",
        "reference": step_ref,
    }


@pytest.mark.parametrize(
    "question",
    [
        "{{ step_1.output.structured }}",
        "{{ step_1.output.structured.report_title }}",
        "{{ step_1.output.structured.source_sections }}",
    ],
)
def test_validate_steps_publish_accepts_contract_proven_structured_question_paths(
    question: str,
) -> None:
    validate_steps(
        [
            _step(
                1,
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(2, input_bindings={"question": question}),
        ],
        require_complete_template_fill_config=True,
    )


@pytest.mark.parametrize(
    ("question", "output_contract"),
    [
        ("{{ step_1.output.structured }}", None),
        ("{{ step_1.output.structured.report_title }}", None),
        (
            "{{ step_1.output.structured.unknown }}",
            _source_sections_contract(),
        ),
        (
            "{{ step_1.output.structured.report_title.value }}",
            _source_sections_contract(),
        ),
        ("{{ step_1.output.unknown }}", _source_sections_contract()),
    ],
)
def test_validate_steps_publish_rejects_unproven_structured_question_paths(
    question: str,
    output_contract: dict[str, object] | None,
) -> None:
    key = question.strip("{} ")
    exc = _assert_validate_steps_rejects(
        [
            _step(1, output_type="json", output_contract=output_contract),
            _step(2, input_bindings={"question": question}),
        ],
        expected_type=FlowStepValidationError,
        match="step_1",
        code="flow_input_binding_unsupported_key",
        step_order=2,
        require_complete_template_fill_config=True,
    )

    assert exc.context == {
        "field": "input_bindings.question",
        "key": key,
    }


def test_validate_steps_preserves_source_ref_schema_error_context() -> None:
    exc = _assert_validate_steps_rejects(
        [
            _step(
                1,
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(
                2,
                input_type="text",
                output_type="text",
                output_mode="compose_text",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "unknown",
                        }
                    ]
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="unknown field",
        code="flow_input_binding_unsupported_key",
        step_order=2,
        require_complete_template_fill_config=True,
    )

    assert exc.context == {"field": "input_bindings", "key": "source_refs"}


def test_validate_steps_accepts_compose_item_template_source_refs() -> None:
    validate_steps(
        [
            _step(
                1,
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(2, output_type="text"),
            _step(
                3,
                input_source="previous_step",
                input_type="text",
                output_type="text",
                output_mode="compose_text",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "source_sections",
                            "item_template": "## {section_title}\n\n{section_body}\n\nKälla: {source_label}",
                        },
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "report_title",
                            "label": "Titel",
                        },
                    ]
                },
            ),
        ]
    )


def test_validate_steps_rejects_compose_array_ref_without_item_template() -> None:
    _assert_validate_steps_rejects(
        [
            _step(
                1,
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(
                2,
                input_type="text",
                output_type="text",
                output_mode="compose_text",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "source_sections",
                        }
                    ]
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="structured array source_refs require item_template",
        code="flow_input_binding_unsupported_key",
        step_order=2,
    )


def test_validate_steps_rejects_compose_item_template_unknown_field() -> None:
    _assert_validate_steps_rejects(
        [
            _step(
                1,
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(
                2,
                input_type="text",
                output_type="text",
                output_mode="compose_text",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "source_sections",
                            "item_template": "{missing}",
                        }
                    ]
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="unknown item field 'missing'",
        code="flow_input_binding_unsupported_key",
        step_order=2,
    )


def test_validate_steps_rejects_item_template_on_llm_step() -> None:
    _assert_validate_steps_rejects(
        [
            _step(
                1,
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(
                2,
                input_type="text",
                output_type="text",
                output_mode="pass_through",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "source_sections",
                            "item_template": "{section_title}",
                        }
                    ]
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="item_template is only supported for output_mode 'compose_text'",
        code="flow_input_binding_unsupported_key",
        step_order=2,
    )


def test_validate_steps_rejects_compose_structured_object_ref_without_string_leaf() -> (
    None
):
    _assert_validate_steps_rejects(
        [
            _step(
                1,
                output_type="json",
                output_contract=_source_sections_contract(),
            ),
            _step(
                2,
                input_type="text",
                output_type="text",
                output_mode="compose_text",
                input_bindings={
                    "source_refs": [{"step_ref": "step_1", "output": "structured"}]
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="without item_template must resolve to a string field",
        code="flow_input_binding_unsupported_key",
        step_order=2,
    )


def test_validate_steps_rejects_audio_document_flow_without_transcript_step():
    with pytest.raises(
        BadRequestException,
        match="Audio document flows must start with a dedicated transcribe_only",
    ):
        validate_steps(
            [
                _step(
                    1,
                    input_source="flow_input",
                    input_type="audio",
                    output_type="json",
                ),
                _step(
                    2,
                    input_source="previous_step",
                    input_type="text",
                    output_mode="render_verbatim",
                    output_type="pdf",
                ),
            ],
            metadata_json=_audio_metadata(),
        )


def test_validate_steps_allows_audio_document_flow_with_transcript_step():
    validate_steps(
        [
            _step(
                1,
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                output_mode="transcribe_only",
            ),
            _step(
                2,
                input_source="previous_step",
                input_type="text",
                output_mode="render_verbatim",
                output_type="pdf",
            ),
        ],
        metadata_json=_audio_metadata(),
    )


def test_validate_steps_rejects_audio_input_without_transcription_metadata():
    with pytest.raises(
        BadRequestException,
        match="Transcription must be enabled when using audio input steps",
    ) as exc_info:
        validate_steps(
            [
                _step(
                    input_source="flow_input",
                    input_type="audio",
                    output_type="text",
                    output_mode="transcribe_only",
                )
            ]
        )
    assert exc_info.value.code == FLOW_AUDIO_TRANSCRIPTION_REQUIRED


def test_validate_steps_rejects_structured_contract_for_all_previous_text_input():
    with pytest.raises(
        BadRequestException,
        match="structured input_contract is not supported with input_source 'all_previous_steps'",
    ):
        validate_steps(
            [
                _step(1, output_type="text"),
                _step(
                    2,
                    input_source="all_previous_steps",
                    input_type="text",
                    output_type="text",
                    input_contract={
                        "type": "object",
                        "properties": {"meeting_context": {"type": "string"}},
                    },
                ),
            ]
        )


def test_validate_steps_allows_string_contract_for_all_previous_text_input():
    validate_steps(
        [
            _step(1, output_type="text"),
            _step(
                2,
                input_source="all_previous_steps",
                input_type="text",
                output_type="text",
                input_contract={"type": "string"},
            ),
        ]
    )


def test_validate_form_schema_rejects_duplicate_field_names_case_insensitive():
    with pytest.raises(BadRequestException, match="already uses that name") as exc_info:
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

    assert exc_info.value.code == "flow_form_field_name_duplicate"
    assert exc_info.value.context == {"field_index": 1, "field_name": "caseid"}


def test_validate_form_schema_allows_scalar_runtime_reserved_field_names():
    validate_form_schema(
        {
            "form_schema": {
                "fields": [
                    {"name": "datum", "type": "date"},
                    {"name": "föregående_steg", "type": "text"},
                    {"name": "indata_text", "type": "text"},
                ],
            }
        }
    )


@pytest.mark.parametrize(
    ("field_name", "code"),
    [
        ("flow", "flow_form_field_name_namespace_head"),
        ("flow_input", "flow_form_field_name_namespace_head"),
        ("step_input", "flow_form_field_name_namespace_head"),
        ("text", "flow_form_field_name_primary_input_key"),
        ("json", "flow_form_field_name_primary_input_key"),
        ("structured", "flow_form_field_name_primary_input_key"),
        ("file_ids", "flow_form_field_name_primary_input_key"),
        ("transcription", "flow_form_field_name_primary_input_key"),
        ("transcript", "flow_form_field_name_primary_input_key"),
        ("transcribed_text", "flow_form_field_name_primary_input_key"),
        ("transkribering", "flow_form_field_name_primary_input_key"),
        ("expected_flow_version", "flow_form_field_name_primary_input_key"),
        ("step_inputs", "flow_form_field_name_primary_input_key"),
    ],
)
def test_validate_form_schema_rejects_runtime_payload_field_names(field_name, code):
    with pytest.raises(BadRequestException) as exc_info:
        validate_form_schema(
            {
                "form_schema": {
                    "fields": [{"name": field_name, "type": "text"}],
                }
            }
        )

    assert exc_info.value.code == code
    assert exc_info.value.context == {"field_index": 0, "field_name": field_name}


def test_validate_form_schema_rejects_step_alias_field_name_with_context():
    with pytest.raises(BadRequestException, match="Names like step_1") as exc_info:
        validate_form_schema(
            {
                "form_schema": {
                    "fields": [{"name": "step_2", "type": "text"}],
                }
            }
        )

    assert exc_info.value.code == "flow_form_field_name_step_alias"
    assert exc_info.value.context == {"field_index": 0, "field_name": "step_2"}


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
                        "template_asset_id": str(uuid4()),
                        "bindings": {"section": "{{step_1.output.text}}"},
                    },
                )
            ]
        )


def test_validate_steps_rejects_template_file_id_identity():
    with pytest.raises(BadRequestException, match="template_file_id is not supported"):
        validate_steps(
            [
                _step(
                    output_mode="template_fill",
                    output_type="docx",
                    output_config={
                        "template_file_id": str(uuid4()),
                        "bindings": {},
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
                        "template_asset_id": str(uuid4()),
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
                    "template_asset_id": str(uuid4()),
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


def test_validate_steps_rejects_http_post_output_before_last_step() -> None:
    with pytest.raises(BadRequestException, match="last step"):
        validate_steps(
            [
                _step(
                    1,
                    output_mode=FlowOutputMode.HTTP_POST,
                    output_config={
                        "url": "https://example.test/hook",
                        "auth": {"mode": "none"},
                    },
                ),
                _step(2),
            ]
        )


def test_validate_steps_allows_http_post_output_on_last_step() -> None:
    validate_steps(
        [
            _step(1, output_type=FlowOutputType.TEXT),
            _step(
                2,
                output_mode=FlowOutputMode.HTTP_POST,
                output_config={
                    "url": "https://example.test/hook",
                    "auth": {"mode": "none"},
                },
            ),
        ]
    )


def test_validate_steps_allows_single_step_http_post_output() -> None:
    validate_steps(
        [
            _step(
                output_mode=FlowOutputMode.HTTP_POST,
                output_config={
                    "url": "https://example.test/hook",
                    "auth": {"mode": "none"},
                },
            )
        ]
    )


def test_normalize_flow_metadata_for_write_maps_legacy_string_type_to_text():
    metadata_json = {
        "form_schema": {
            "fields": [
                {"name": "CustomerName", "type": "string"},
                {"name": "Category", "type": "select"},
            ]
        }
    }

    normalized = normalize_flow_metadata_for_write(metadata_json)

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


def test_validate_variable_alias_collisions_still_rejects_reserved_step_names():
    with pytest.raises(BadRequestException, match="that name is reserved"):
        validate_variable_alias_collisions(
            steps=[_step(user_description="datum")],
            metadata_json={
                "form_schema": {
                    "fields": [
                        {"name": "mötesdatum", "type": "date"},
                    ]
                }
            },
        )
