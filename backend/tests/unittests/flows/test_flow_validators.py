from __future__ import annotations

import itertools
from collections.abc import Iterator
from uuid import uuid4

import jsonschema
import pytest

from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
    flow_step_validation_view_from_flow_step,
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
    _is_plain_tree,
    _validate_step_mapped_execution,
    collect_step_graph_issues,
    template_bound_path_made_ok,
    template_bound_path_ok,
    validate_form_schema,
    validate_steps,
)
from eneo.flows.flow_validators_form import validate_variable_alias_collisions
from eneo.main.exceptions import BadRequestException
from tests.unittests.flows.schema_witness_support import (
    all_plain,
    local_listener,
    witness,
)
from tests.unittests.flows.test_input_binding_contract_rules import (
    _wildcard_projection_case,
)


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


@pytest.mark.parametrize(
    "updates",
    [
        {"output_mode": "compose_text", "output_type": "text"},
        {"output_mode": "http_post", "output_config": {"url": "https://example.com"}},
        {
            "step_order": 2,
            "input_source": "previous_step",
            "input_type": "json",
            "input_config": {"item_map": {"enabled": True, "max_items": 2}},
        },
        {
            "input_type": "document",
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "execution_mode": "per_source",
                    "max_files": 2,
                }
            },
        },
    ],
)
@pytest.mark.parametrize("mode", ["process_each_section", "summarize"])
def test_text_processing_rejects_incompatible_step_or_nested_mapping(updates, mode):
    step = _step(**updates)
    step.input_config = {
        **(step.input_config or {}),
        "text_processing": {"mode": mode},
    }
    view = flow_step_validation_view_from_flow_step(step)

    with pytest.raises(FlowStepValidationError) as exc_info:
        _validate_step_mapped_execution(step=view)

    assert exc_info.value.code == FlowGraphIssueCode.FLOW_STEP_INVALID.value
    if "input_config" in updates:
        assert "cannot be nested" in str(exc_info.value)


@pytest.mark.parametrize("mode", ["process_each_section", "summarize"])
def test_text_processing_requires_an_authored_array_of_records(mode):
    step = _step(input_config={"text_processing": {"mode": mode}})
    with pytest.raises(FlowStepValidationError, match="array"):
        _validate_step_mapped_execution(
            step=flow_step_validation_view_from_flow_step(step)
        )


@pytest.mark.parametrize("mode", [None, "summarize", "process_each_section"])
def test_section_index_scope_at_existing_authoring_variable_validation(mode):
    from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
    from eneo.flows.ai_builder.ai_builder_validation_references import (
        validate_variable_references,
    )
    from eneo.flows.flow_authoring_spec import (
        AssistantSpec,
        FlowDraftSpecCore,
        StepSpec,
    )
    from eneo.flows.flow_variable_definitions import flow_variable_definition_manifest

    step = StepSpec(
        plan_step_ref="step_a",
        name="Extract",
        assistant_spec=AssistantSpec(instructions="S{{ section_index }}-"),
        input_source="flow_input",
        input_config={"text_processing": {"mode": mode}} if mode else None,
    )
    result = SpecValidationResult()
    validate_variable_references(
        FlowDraftSpecCore(flow_name="Sections", steps=[step]), result
    )
    variables = flow_variable_definition_manifest(step.input_config)[
        "reservedRuntimeVariables"
    ]
    assert ("section_index" in variables) == (mode == "process_each_section")

    if mode == "process_each_section":
        assert result.valid
    else:
        assert [error.code for error in result.errors] == ["unknown_variable_reference"]
        assert "'section_index'" in result.errors[0].message


@pytest.mark.parametrize(
    "processing",
    [
        {"mode": "invalid"},
        {"mode": "process_each_section", "section_count": 3},
    ],
)
def test_malformed_section_config_returns_structured_authoring_error(processing):
    from eneo.flows.ai_builder.ai_builder_validator import validate_spec
    from eneo.flows.flow_authoring_spec import (
        AssistantSpec,
        FlowDraftSpecCore,
        StepSpec,
    )
    from eneo.flows.flow_variable_definitions import (
        RESERVED_RUNTIME_VARIABLES,
        runtime_variables_for_step,
    )

    input_config = {"text_processing": processing}
    spec = FlowDraftSpecCore(
        flow_name="Sections",
        steps=[
            StepSpec(
                plan_step_ref="extract",
                name="Extract records",
                assistant_spec=AssistantSpec(
                    instructions="Extract {{ flow_input.text }}."
                ),
                input_source="flow_input",
                input_config=input_config,
            )
        ],
    )

    result = validate_spec(spec)

    assert not result.valid
    assert [error.code for error in result.errors] == ["flow_step_invalid"]
    assert result.errors[0].step_ref == "extract"
    assert runtime_variables_for_step(input_config) == RESERVED_RUNTIME_VARIABLES


def _form_metadata(*field_names: str) -> dict:
    return {
        "form_schema": {
            "fields": [
                {"name": field_name, "type": "text"} for field_name in field_names
            ]
        }
    }


def _expected_boundary_context(
    exc: BadRequestException, facts: dict[str, object]
) -> dict[str, object]:
    """The exact context the boundary emits: case facts + canonical identity."""
    expected: dict[str, object] = dict(facts)
    expected["issue_code"] = exc.code
    if isinstance(exc, FlowStepValidationError):
        expected["step_order"] = exc.step_order
    return expected


def _assert_validate_steps_rejects(
    steps: list[FlowStep],
    *,
    expected_type: type[BadRequestException],
    match: str,
    code: str | None = None,
    step_order: int | None = None,
    metadata_json: dict | None = None,
    require_complete_template_fill_config: bool = False,
    prompts: dict[int, str] | None = None,
) -> BadRequestException:
    with pytest.raises(BadRequestException, match=match) as exc_info:
        validate_steps(
            steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=require_complete_template_fill_config,
            prompt_templates=prompts,
        )

    exc = exc_info.value
    assert type(exc) is expected_type
    if code is not None:
        assert exc.code == code
    else:
        # The boundary contract now always carries the canonical issue code
        # so clients can translate; the identity also rides in context.
        assert isinstance(exc.code, str) and exc.code
        context = getattr(exc, "context", None)
        assert isinstance(context, dict) and context.get("issue_code") == exc.code
        if isinstance(exc, FlowStepValidationError):
            assert context.get("step_order") == exc.step_order
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
        (
            [
                _step(1),
                _step(
                    2,
                    input_source="http_get",
                    input_bindings={"question": "Svar: {{ step_1.output.text }}"},
                ),
            ],
            "cannot be combined with input_bindings",
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
        "{{ datum }}",
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
    "question",
    [
        "{{ indata_text }}",
        "{{ flow_input.text }}",
        "{{ flow_input.json.rader }}",
        "{{ flow.input.structured }}",
    ],
)
def test_validate_steps_publish_refuses_the_run_text_a_form_run_never_collects(
    question: str,
) -> None:
    step = _step(input_bindings={"question": question})
    metadata_json = _form_metadata("case_id")

    # A draft save is not refused: the form is still being edited.
    validate_steps([step], metadata_json=metadata_json)

    exc = _assert_validate_steps_rejects(
        [step],
        expected_type=FlowStepValidationError,
        match="form fields",
        code="flow_input_alias_not_received",
        step_order=1,
        metadata_json=metadata_json,
        require_complete_template_fill_config=True,
    )
    assert exc.context == {
        "field": "input_bindings.question",
        "reference": question.strip("{} "),
        "issue_code": "flow_input_alias_not_received",
        "step_order": 1,
    }


_HTTP_AUTH = {"auth": {"mode": "none"}}
_UPLOAD_RUN = {"runtime_input": {"enabled": True, "input_format": "document"}}


@pytest.mark.parametrize(
    ("updates", "field", "reference"),
    [
        pytest.param(
            {
                "input_source": "http_get",
                "input_config": {
                    "url": "https://example.com/?q={{ flow_input.text }}",
                    **_HTTP_AUTH,
                },
            },
            "input_config",
            "flow_input.text",
            id="http-get-url",
        ),
        pytest.param(
            {
                "input_source": "http_get",
                "input_config": {
                    "url": "https://example.com/",
                    "custom_headers": [{"name": "X-Q", "value": "{{ indata_text }}"}],
                    **_HTTP_AUTH,
                },
            },
            "input_config",
            "indata_text",
            id="http-get-header",
        ),
        pytest.param(
            {
                "output_mode": "http_post",
                "output_config": {
                    "url": "https://example.org/hook/{{indata_text}}",
                    "timeout_seconds": 25,
                    **_HTTP_AUTH,
                },
            },
            "output_config",
            "indata_text",
            id="http-post-url",
        ),
        pytest.param(
            {
                "output_mode": "http_post",
                "output_config": {
                    "url": "https://example.org/hook",
                    "timeout_seconds": 25,
                    "body": {
                        "mode": "text_template",
                        "template": '{"m": "{{ flow.input . text }}"}',
                    },
                    **_HTTP_AUTH,
                },
            },
            "output_config",
            "flow.input . text",
            id="http-post-body-spaced-path",
        ),
    ],
)
def test_validate_steps_publish_refuses_run_text_read_in_an_http_config_of_a_form_run(
    updates: dict, field: str, reference: str
) -> None:
    exc = _assert_validate_steps_rejects(
        [_step(**updates)],
        expected_type=FlowStepValidationError,
        match="free-text input",
        code="flow_input_alias_not_received",
        step_order=1,
        metadata_json=_form_metadata("case_id"),
        require_complete_template_fill_config=True,
    )

    assert exc.context["field"] == field
    assert exc.context["reference"] == reference


def test_validate_steps_publish_accepts_run_text_in_a_free_text_runs_http_get() -> None:
    validate_steps(
        [
            _step(
                input_source="http_get",
                input_config={
                    "url": "https://example.com/?q={{ flow_input.text }}",
                    **_HTTP_AUTH,
                },
            )
        ],
        require_complete_template_fill_config=True,
    )


def test_publish_advice_for_an_upload_run_fits_the_step_that_reads() -> None:
    # The step taking the upload reads it as step_input.text; another step
    # reads an earlier step's output.
    taking_upload = _step(input_type="document", input_config=_UPLOAD_RUN)
    other = _step(step_order=2, input_bindings={"question": "{{ indata_text }}"})

    upload_exc = _assert_validate_steps_rejects(
        [taking_upload],
        expected_type=FlowStepValidationError,
        match="free-text input",
        step_order=1,
        require_complete_template_fill_config=True,
        prompts={1: "Sammanfatta {{ indata_text }}."},
    )
    other_exc = _assert_validate_steps_rejects(
        [taking_upload, other],
        expected_type=FlowStepValidationError,
        match="free-text input",
        step_order=2,
        require_complete_template_fill_config=True,
    )

    assert "Read the upload with {{ step_input.text }}." in str(upload_exc)
    assert "Read an earlier step's output instead." in str(other_exc)
    assert "step_input.text" not in str(other_exc)


def test_publish_refusal_states_what_the_run_form_declares_and_no_runtime_claim() -> (
    None
):
    exc = _assert_validate_steps_rejects(
        [_step(input_bindings={"question": "{{ indata_text }}"})],
        expected_type=FlowStepValidationError,
        match="free-text input",
        metadata_json=_form_metadata("case_id"),
        require_complete_template_fill_config=True,
    )

    message = str(exc)
    assert (
        "The run dialog and the documented run contract supply only the declared "
        "form fields (and uploads), so publish refuses a step that reads run text "
        "on such a flow."
    ) in message
    # No claim about what a runtime payload can hold.
    for claim in ("never", "no client", "supplies it", "nothing else"):
        assert claim not in message


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

    _expected_context = context
    assert exc.context == _expected_boundary_context(exc, _expected_context)


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

    _expected_context = {
        "field": "input_bindings.question",
        "reference": question.strip("{} "),
    }
    assert exc.context == _expected_boundary_context(exc, _expected_context)


# A question's template head is read by the template grammar (`step_<order>`,
# ASCII, no leading zero), a source ref's step_ref by the runtime's own (any
# decimal numeral); neither raises on an unusual digit.
@pytest.mark.parametrize(
    ("location", "reference", "code"),
    [
        ("question", "step_01", "flow_input_binding_invalid_step_reference"),
        ("question", "step_\u0661", "flow_input_binding_invalid_step_reference"),
        ("question", "step_\u00b9", "flow_input_binding_invalid_step_reference"),
        ("question", "step_\uff13", "flow_input_binding_invalid_step_reference"),
        ("source_ref", "step_\u00b9", "flow_input_binding_invalid_step_reference"),
        ("source_ref", "step_\uff13", "flow_input_binding_future_step_reference"),
        ("source_ref", "step_03", "flow_input_binding_future_step_reference"),
        ("source_ref", "step_00", "flow_input_binding_unknown_step_order"),
        ("source_ref", "step_01", None),
        ("source_ref", "step_\u0662", None),
    ],
)
def test_validate_steps_draft_reads_each_binding_with_its_own_step_grammar(
    location: str, reference: str, code: str | None
) -> None:
    if location == "question":
        bindings = {"question": "Use {{ " + reference + ".output.text }}"}
    else:
        bindings = {"source_refs": [{"step_ref": reference, "output": "text"}]}
    steps = [_step(1), _step(2), _step(3, input_bindings=bindings)]

    if code is None:
        validate_steps(steps, require_complete_template_fill_config=False)
        return
    exc = _assert_validate_steps_rejects(
        steps,
        expected_type=FlowStepValidationError,
        match="step",
        code=code,
        step_order=3,
        require_complete_template_fill_config=False,
    )
    assert exc.context is not None and exc.context["reference"].startswith(reference)


@pytest.mark.parametrize("location", ["question", "source_ref"])
@pytest.mark.parametrize(
    ("reference", "code"),
    [
        ("step_bad", "flow_input_binding_invalid_step_reference"),
        ("step_9", "flow_input_binding_future_step_reference"),
        ("step_0", "flow_input_binding_unknown_step_order"),
        ("step_9.output.structured.title", "flow_input_binding_future_step_reference"),
    ],
)
def test_validate_steps_draft_preserves_binding_repair_identity(
    location: str,
    reference: str,
    code: str,
) -> None:
    if location == "question":
        bindings = {"question": "Use {{" + reference + "}}"}
        field = "input_bindings.question"
        repaired_bindings = {"question": "Use {{step_1}}"}
    else:
        bindings = {
            "source_refs": [
                {"step_ref": "step_1", "output": "text"},
                {"step_ref": reference, "output": "text"},
            ]
        }
        field = "input_bindings.source_refs[1].step_ref"
        repaired_bindings = {
            "source_refs": [
                {"step_ref": "step_1", "output": "text"},
                {"step_ref": "step_1", "output": "text"},
            ]
        }
    producer = _step(1, output_type="text")
    consumer = _step(2, input_bindings=bindings)
    exc = _assert_validate_steps_rejects(
        [producer, consumer],
        expected_type=FlowStepValidationError,
        match="step",
        code=code,
        step_order=2,
        require_complete_template_fill_config=False,
    )
    assert exc.context == {
        "issue_code": code,
        "step_order": 2,
        "field": field,
        "reference": reference,
    }
    validate_steps(
        [producer, consumer.model_copy(update={"input_bindings": repaired_bindings})],
        require_complete_template_fill_config=False,
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


@pytest.mark.parametrize(
    "step",
    [
        _step(
            input_type="text",
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "execution_mode": "per_source",
                    "max_files": 2,
                }
            },
        ),
        _step(
            input_type="text",
            input_config={"item_map": {"enabled": True, "max_items": 2}},
        ),
    ],
    ids=["unsupported_per_source", "unsupported_per_item"],
)
def test_validate_steps_rejects_mapped_modes_runtime_cannot_dispatch(
    step: FlowStep,
) -> None:
    _assert_validate_steps_rejects(
        [step],
        expected_type=FlowStepValidationError,
        match="mapped execution requires",
        step_order=1,
        require_complete_template_fill_config=True,
    )


def test_validate_steps_rejects_simultaneous_mapped_modes() -> None:
    _assert_validate_steps_rejects(
        [
            _step(1),
            _step(
                2,
                input_type="json",
                input_config={
                    "runtime_input": {
                        "enabled": True,
                        "execution_mode": "per_source",
                        "max_files": 3,
                    },
                    "item_map": {"enabled": True, "max_items": 5},
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="only one mapped execution mode",
        step_order=2,
        require_complete_template_fill_config=True,
    )


@pytest.mark.parametrize(
    ("input_config", "message"),
    [
        (
            {"item_map": "bad"},
            "Step input_config.item_map must be an object.",
        ),
        (
            {
                "runtime_input": {
                    "enabled": True,
                    "execution_mode": "per_source",
                    "max_files": "bad",
                }
            },
            "Step input_config.runtime_input is invalid.",
        ),
    ],
    ids=["item_map", "runtime_input"],
)
def test_collect_step_graph_issues_projects_malformed_mapped_config(
    input_config: dict[str, object],
    message: str,
) -> None:
    issues = collect_step_graph_issues(
        flow_step_validation_views_from_flow_steps([_step(input_config=input_config)]),
        require_complete_template_fill_config=True,
    )

    assert len(issues) == 1
    issue = issues[0]
    assert issue.step_order == 1
    assert issue.code is FlowGraphIssueCode.FLOW_STEP_INVALID
    assert issue.exception_kind == "bad_request"
    assert issue.message == message


def test_validate_steps_source_refs_do_not_satisfy_runtime_input_consumption() -> None:
    with pytest.raises(
        BadRequestException,
        match="explicit question bindings must reference step_input",
    ) as exc_info:
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

    # The motivating raw sentence now carries an exact boundary identity the
    # client translates and navigates by.
    exc = exc_info.value
    assert exc.code == "flow_input_binding_runtime_input_unused"
    assert isinstance(exc, FlowStepValidationError)
    assert exc.step_order == 2
    assert exc.context == {
        "issue_code": "flow_input_binding_runtime_input_unused",
        "step_order": 2,
    }


def test_validate_steps_rejects_unsupported_binding_keys_only_when_publish_strict():
    step = _step(input_bindings={"text": "{{ flow_input.text }}"})

    validate_steps([step], require_complete_template_fill_config=False)

    with pytest.raises(BadRequestException) as exc_info:
        validate_steps([step], require_complete_template_fill_config=True)

    assert exc_info.value.code == "flow_input_binding_unsupported_key"
    _expected_context = {
        "field": "input_bindings",
        "key": "text",
    }
    assert exc_info.value.context == _expected_boundary_context(
        exc_info.value, _expected_context
    )


def test_validate_steps_rejects_incompatible_implicit_json_contract():
    consumer_contract = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    }
    producer = _step(output_contract=consumer_contract)
    consumer = _step(2, input_type="json", input_contract=consumer_contract)
    validate_steps([producer, consumer])

    producer.output_contract = {
        "type": "object",
        "properties": {"different": {"type": "string"}},
        "required": ["different"],
    }
    _assert_validate_steps_rejects(
        [producer, consumer],
        expected_type=FlowStepValidationError,
        match="input_contract",
        code=FlowGraphIssueCode.INPUT_CONTRACT_SOURCE_MISMATCH.value,
        step_order=2,
    )


@pytest.mark.parametrize(
    ("produced", "consumed", "compatible"),
    [
        ({"type": "string", "description": "New wording"}, {"type": "string"}, True),
        ({"type": "string"}, {"type": ["string", "null"]}, True),
        ({"type": ["string", "null"]}, {"type": "string"}, False),
        ({"type": "integer"}, {"type": "number"}, True),
        ({"type": "number"}, {"type": "integer"}, False),
        ({"type": "number"}, {"type": "string"}, False),
        ({"type": "array", "items": {"type": "string"}}, {"type": "array"}, True),
        ({"type": "array"}, {"type": "array", "items": {"type": "string"}}, False),
        (
            {"type": "array", "items": {"type": "number"}},
            {"type": "array", "items": {"type": "string"}},
            False,
        ),
        (
            {"type": "object", "properties": {"name": {"type": "string"}}},
            {"type": "object", "required": ["name"]},
            False,
        ),
        (
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
            {"type": "object", "properties": {"name": {"type": "string"}}},
            True,
        ),
        (
            {"type": "object", "additionalProperties": {"type": "integer"}},
            {"type": "object", "additionalProperties": {"type": "number"}},
            True,
        ),
        (
            {"type": "object", "properties": {"extra": {"type": "string"}}},
            {"type": "object", "additionalProperties": False},
            False,
        ),
        (
            {"type": "object", "additionalProperties": False},
            {"type": "object", "properties": {"optional": {"type": "string"}}},
            True,
        ),
        (
            {"type": "string", "pattern": "^a"},
            {"type": "string", "pattern": "^a"},
            True,
        ),
        (
            {"type": "string", "pattern": "^b"},
            {"type": "string", "pattern": "^a"},
            False,
        ),
        ({"const": 1}, {"const": True}, False),
        ({"enum": [0]}, {"enum": [False]}, False),
    ],
)
def test_validate_steps_implicit_json_contract_subset(produced, consumed, compatible):
    def contract(value):
        return {
            "type": "object",
            "properties": {"value": value},
            "required": ["value"],
            "additionalProperties": False,
        }

    steps = [
        _step(output_contract=contract(produced)),
        _step(2, input_type="json", input_contract=contract(consumed)),
    ]
    if compatible:
        validate_steps(steps)
    else:
        _assert_validate_steps_rejects(
            steps,
            expected_type=FlowStepValidationError,
            match="input_contract",
            code=FlowGraphIssueCode.INPUT_CONTRACT_SOURCE_MISMATCH.value,
            step_order=2,
        )


@pytest.mark.parametrize("produced", [None, {"type": "object"}])
def test_validate_steps_rejects_unproven_implicit_json_contract(produced):
    _assert_validate_steps_rejects(
        [
            _step(output_contract=produced),
            _step(
                2,
                input_type="json",
                input_contract={"type": "object", "required": ["summary"]},
            ),
        ],
        expected_type=FlowStepValidationError,
        match="input_contract",
        code=FlowGraphIssueCode.INPUT_CONTRACT_SOURCE_MISMATCH.value,
        step_order=2,
    )


def test_validate_steps_implicit_contract_reports_malformed_binding():
    with pytest.raises(FlowStepValidationError, match="source_refs"):
        validate_steps(
            [
                _step(output_contract={"type": "object"}),
                _step(
                    2,
                    input_type="json",
                    input_contract={"type": "object"},
                    input_bindings={"source_refs": ["invalid"]},
                ),
            ]
        )


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


def test_validate_steps_accepts_structured_source_refs_with_projection_contract():
    validate_steps(
        [
            _step(
                1,
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            ),
            _step(
                2,
                input_type="json",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "title",
                        }
                    ]
                },
                input_contract={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            ),
        ]
    )


@pytest.mark.parametrize("output_mode", ["pass_through", "compose_text"])
@pytest.mark.parametrize("publish_strict", [False, True])
def test_wildcard_projection_refuses_text_consumers(output_mode, publish_strict):
    bindings, source, _ = _wildcard_projection_case()
    _assert_validate_steps_rejects(
        [
            _step(1, output_contract=source),
            _step(
                2,
                input_type="text",
                output_type="text",
                output_mode=output_mode,
                input_bindings=bindings,
            ),
        ],
        expected_type=FlowStepValidationError,
        match="wildcards require a structured JSON projection",
        code="flow_input_binding_unsupported_key",
        step_order=2,
        require_complete_template_fill_config=publish_strict,
    )


@pytest.mark.parametrize("field_path", ["sections.*", "sections.*.rows.*.values"])
def test_runtime_input_preserves_wildcard_binding_error_code(field_path):
    bindings, source, _ = _wildcard_projection_case()
    bindings["source_refs"][0]["field_path"] = field_path
    _assert_validate_steps_rejects(
        [
            _step(1, output_contract=source),
            _step(
                2,
                input_type="text",
                output_type="text",
                input_bindings=bindings,
                input_config={
                    "runtime_input": {"enabled": True, "input_format": "document"}
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="field_path",
        code="flow_input_binding_unsupported_key",
        step_order=2,
        require_complete_template_fill_config=True,
    )


def test_validate_steps_rejects_structured_source_refs_without_input_contract():
    producer_contract = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    }

    exc = _assert_validate_steps_rejects(
        [
            _step(1, output_type="json", output_contract=producer_contract),
            _step(
                2,
                input_type="json",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "title",
                        }
                    ]
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="structured JSON source_refs require input_contract",
        code="flow_input_contract_inapplicable",
        step_order=2,
    )

    assert exc.context["conflict"] == "input_bindings.source_refs"


def test_validate_steps_rejects_structured_projection_without_producer_contract():
    _assert_validate_steps_rejects(
        [
            _step(1, output_type="json"),
            _step(
                2,
                input_type="json",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "title",
                        }
                    ]
                },
                input_contract={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="requires a producer output_contract",
        code="flow_input_binding_unsupported_key",
        step_order=2,
    )


def test_validate_steps_rejects_structured_projection_unknown_field_path():
    _assert_validate_steps_rejects(
        [
            _step(
                1,
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
            ),
            _step(
                2,
                input_type="json",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "missing",
                        }
                    ]
                },
                input_contract={"type": "object"},
            ),
        ],
        expected_type=FlowStepValidationError,
        match="field_path 'missing' is absent",
        code="flow_input_binding_unsupported_key",
        step_order=2,
    )


def test_validate_steps_rejects_structured_projection_path_collision():
    producer_contract = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
    }

    _assert_validate_steps_rejects(
        [
            _step(1, output_type="json", output_contract=producer_contract),
            _step(2, output_type="json", output_contract=producer_contract),
            _step(
                3,
                input_type="json",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "title",
                        },
                        {
                            "step_ref": "step_2",
                            "output": "structured",
                            "field_path": "title",
                        },
                    ]
                },
                input_contract={"type": "object"},
            ),
        ],
        expected_type=FlowStepValidationError,
        match="source_ref path collision at 'title'",
        code="flow_input_binding_unsupported_key",
        step_order=3,
    )


def test_validate_steps_rejects_mismatched_structured_projection_contract():
    _assert_validate_steps_rejects(
        [
            _step(
                1,
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
            ),
            _step(
                2,
                input_type="json",
                input_bindings={
                    "source_refs": [
                        {
                            "step_ref": "step_1",
                            "output": "structured",
                            "field_path": "title",
                        }
                    ]
                },
                input_contract={
                    "type": "object",
                    "properties": {"title": {"type": "number"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            ),
        ],
        expected_type=FlowStepValidationError,
        match="input_contract does not match the exact structured source_ref projection",
        code="flow_input_contract_inapplicable",
        step_order=2,
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


# The runtime reads a source ref's number as any decimal numeral.
@pytest.mark.parametrize(
    "step_ref", ["step_1", "step_01", "step_\u0661", "Collect intake"]
)
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


def test_validate_steps_accepts_nullable_scalar_structured_source_ref() -> None:
    validate_steps(
        [
            _step(
                1,
                user_description="Collect intake",
                output_type="json",
                output_contract={
                    "type": "object",
                    "properties": {"classification": {"type": ["string", "null"]}},
                    "required": ["classification"],
                },
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
                            "field_path": "classification",
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

    _expected_context = {
        "field": "input_bindings.source_refs[1].step_ref",
        "reference": step_ref,
    }
    assert exc.context == _expected_boundary_context(exc, _expected_context)


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

    _expected_context = {
        "field": "input_bindings.question",
        "key": key,
    }
    assert exc.context == _expected_boundary_context(exc, _expected_context)


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

    _expected_context = {"field": "input_bindings", "key": "source_refs"}
    assert exc.context == _expected_boundary_context(exc, _expected_context)


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
    with pytest.raises(BadRequestException) as exc_info:
        validate_form_schema(
            {
                "form_schema": {
                    "fields": [{"name": "step_2", "type": "text"}],
                }
            }
        )

    assert str(exc_info.value) == (
        "Form field 1 is named 'step_2'. Names like step_1 are reserved for "
        "Flow step aliases. Use a descriptive field name instead."
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


@pytest.mark.parametrize(
    "expression",
    [
        "step_1.output.structured",
        "step_1.output.structured.details",
        "step_1.output.structured.items",
        "step_1.output",
        "flow_input",
        "flow_input.recipients",
        "recipients",
        "indata_json",
    ],
)
def test_template_fill_publish_rejects_non_scalar_bindings(expression: str) -> None:
    steps = [
        _step(
            output_contract={
                "type": "object",
                "properties": {
                    "details": {"type": "object", "properties": {}},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
            }
        ),
        _step(
            step_order=2,
            output_type="docx",
            output_mode="template_fill",
            output_config={
                "template_asset_id": str(uuid4()),
                "bindings": {"body": "{{" + expression + "}}"},
            },
        ),
    ]
    with pytest.raises(FlowStepValidationError, match="scalar"):
        validate_steps(
            steps,
            metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "recipients",
                            "type": "multiselect",
                            "options": ["A", "B"],
                        },
                    ]
                }
            },
            require_complete_template_fill_config=True,
        )


@pytest.mark.parametrize(
    "title_schema",
    [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "string", "title": "Titel", "description": "Ärendets titel."},
        # Every other keyword only narrows a node that already has one type.
        {"type": "string", "minLength": 1},
        {"type": "string", "enum": ["a", "b"]},
        {"type": "string", "pattern": "^A", "format": "date"},
        {"type": "integer", "minimum": 0},
        {"type": "string", "allOf": [{"minLength": 1}]},
        {"type": "string", "anyOf": [{"minLength": 1}, {"pattern": "^A"}]},
    ],
)
def test_template_fill_publish_accepts_a_required_field_of_one_type(
    title_schema,
) -> None:
    validate_steps(
        [
            _step(
                output_contract={
                    "type": "object",
                    "properties": {
                        "details": {
                            "type": "object",
                            "properties": {
                                "title": title_schema,
                            },
                            "required": ["title"],
                        },
                        "count": {"type": "integer"},
                    },
                    "required": ["details", "count"],
                }
            ),
            _step(
                step_order=2,
                output_type="docx",
                output_mode="template_fill",
                output_config={
                    "template_asset_id": str(uuid4()),
                    "bindings": {
                        "title": "{{step_1.output.structured.details.title}}",
                        "count": "{{step_1.output.structured.count}}",
                        "body": "{{step_1.output.text}}",
                        "date": "{{datum}}",
                        "author": "{{flow_input.author}}",
                        "author_alias": "{{author}}",
                    },
                },
            ),
        ],
        metadata_json=_form_metadata("author"),
        require_complete_template_fill_config=True,
    )


def test_template_fill_publish_accepts_the_free_text_of_a_free_text_run() -> None:
    validate_steps(
        [
            _step(),
            _step(
                step_order=2,
                output_type="docx",
                output_mode="template_fill",
                output_config={
                    "template_asset_id": str(uuid4()),
                    "bindings": {
                        "body": "{{step_1.output.text}}",
                        "input": "{{flow_input.text}}",
                    },
                },
            ),
        ],
        require_complete_template_fill_config=True,
    )


def _template_fill_over_contract(contract: dict, *, binding: str) -> list[FlowStep]:
    return [
        _step(output_contract=contract),
        _step(
            step_order=2,
            output_type="docx",
            output_mode="template_fill",
            output_config={
                "template_asset_id": str(uuid4()),
                "bindings": {"title": binding},
            },
        ),
    ]


# The `$ref`s of the fixtures below are local: they must resolve, or the contract is
# refused by the contract owner (a reference to nowhere) before the field is looked at.
_LOCAL_TARGETS = {
    "$defs": {name: {"type": "string"} for name in ("title", "details", "result", "t")}
}


def _nested(leaf: dict, *, above: dict | None = None) -> dict:
    """A step result with `leaf` at `details.title`; `above` overrides `details`."""

    details = {
        "type": "object",
        "properties": {"title": leaf},
        "required": ["title"],
        **(above or {}),
    }
    return {
        "type": "object",
        "properties": {"details": details},
        "required": ["details"],
    }


# One entry per way the field itself can fail to have exactly one type.
_UNPLAIN_LEAVES = [
    pytest.param({"type": ["string", "null"]}, id="type-list-with-null"),
    pytest.param({"type": ["null", "integer"]}, id="type-list-null-first"),
    pytest.param({"type": ["string"]}, id="type-list-of-one"),
    pytest.param({"type": ["string", "number"]}, id="type-list"),
    pytest.param({"type": "null"}, id="null"),
    pytest.param({"enum": ["a", "b"]}, id="untyped-enum"),
    pytest.param({"enum": ["a", None]}, id="untyped-enum-with-null"),
    pytest.param({"const": "final"}, id="untyped-const"),
    pytest.param({"const": None}, id="untyped-const-null"),
    pytest.param({"anyOf": [{"type": "string"}, {"type": "null"}]}, id="untyped-anyof"),
    pytest.param(
        {"oneOf": [{"type": "string"}, {"type": "number"}]}, id="untyped-oneof"
    ),
    pytest.param({"allOf": [{"type": "string"}]}, id="untyped-allof"),
    pytest.param({"$ref": "#/$defs/title"}, id="ref"),
    pytest.param({"type": "string", "$ref": "#/$defs/title"}, id="ref-beside-type"),
    pytest.param({"description": "Titel"}, id="missing-type"),
    pytest.param({}, id="empty"),
]


@pytest.mark.parametrize("leaf", _UNPLAIN_LEAVES)
def test_template_fill_publish_rejects_a_field_without_exactly_one_type(
    leaf: dict,
) -> None:
    # The fill step refuses null and a missing key and treats "" as an
    # omission. Keywords only narrow a node, so exactly one non-null type
    # excludes null; without it, nothing on the node does.
    steps = _template_fill_over_contract(
        {**_nested(leaf), **_LOCAL_TARGETS},
        binding="{{step_1.output.structured.details.title}}",
    )

    with pytest.raises(FlowStepValidationError) as exc_info:
        validate_steps(steps, require_complete_template_fill_config=True)

    message = str(exc_info.value)
    assert exc_info.value.step_order == 2
    assert "template binding 'title'" in message
    # A field the scalar rule already refuses keeps that message.
    if "scalar" not in message:
        assert "'details.title' of step 1" in message
        assert "required field of one type" in message
        assert "empty string" in message or "valid value" in message
    # The same graph is fine while it is only a draft.
    validate_steps(steps)


# One entry per way the objects above the field, or the step's result, can
# fail to be an object that requires the next key.
_UNPLAIN_ABOVE = [
    pytest.param(
        _nested({"type": "string"}, above={"type": ["object", "null"]}),
        id="nullable-object",
    ),
    pytest.param(
        _nested({"type": "string"}, above={"type": ["object"]}), id="type-list-of-one"
    ),
    pytest.param(
        {
            "type": "object",
            "properties": {
                "details": {
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                }
            },
            "required": ["details"],
        },
        id="object-without-type",
    ),
    pytest.param(
        {
            "type": ["object", "null"],
            "properties": _nested({"type": "string"})["properties"],
            "required": ["details"],
        },
        id="nullable-result",
    ),
    pytest.param(
        {
            "properties": _nested({"type": "string"})["properties"],
            "required": ["details"],
        },
        id="result-without-type",
    ),
    pytest.param(
        {
            "type": "object",
            "properties": _nested({"type": "string"})["properties"],
        },
        id="object-not-required-no-list",
    ),
    pytest.param(
        {
            "type": "object",
            "properties": _nested({"type": "string"})["properties"],
            "required": [],
        },
        id="object-not-required",
    ),
    pytest.param(
        _nested({"type": "string"}, above={"required": []}), id="field-not-required"
    ),
    pytest.param(
        _nested({"type": "string"}, above={"$ref": "#/$defs/details"}),
        id="object-ref",
    ),
    pytest.param(
        {**_nested({"type": "string"}), "$ref": "#/$defs/result"}, id="result-ref"
    ),
]


@pytest.mark.parametrize("contract", _UNPLAIN_ABOVE)
def test_template_fill_publish_rejects_a_field_under_an_object_without_one_type(
    contract: dict,
) -> None:
    steps = _template_fill_over_contract(
        {**contract, **_LOCAL_TARGETS},
        binding="{{step_1.output.structured.details.title}}",
    )

    with pytest.raises(FlowStepValidationError) as exc_info:
        validate_steps(steps, require_complete_template_fill_config=True)

    message = str(exc_info.value)
    assert "template binding 'title' reads 'details.title' of step 1" in message
    assert "required field of one type" in message
    validate_steps(steps)


def test_template_fill_publish_accepts_constraints_on_the_objects_above_the_field() -> (
    None
):
    # An ancestor's own keywords only narrow it; the one that forbids `secret`
    # is not the placeholder's business and is not refused.
    steps = _template_fill_over_contract(
        _nested(
            {"type": "string", "minLength": 1},
            above={
                "allOf": [{"not": {"required": ["secret"]}}],
                "anyOf": [{"required": ["title"]}],
                "minProperties": 1,
                "additionalProperties": False,
            },
        ),
        binding="{{step_1.output.structured.details.title}}",
    )

    validate_steps(steps, require_complete_template_fill_config=True)


def test_template_fill_publish_accepts_an_unbound_field_of_any_shape() -> None:
    steps = _template_fill_over_contract(
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "note": {"type": ["string", "null"]},
                "extra": {"enum": [None, "x"], "minLength": 2},
            },
            "required": ["title"],
        },
        binding="{{step_1.output.structured.title}}",
    )

    validate_steps(steps, require_complete_template_fill_config=True)


def _null_instances(path: tuple[str, ...]) -> list[object]:
    """Instances that put null, or nothing, at each depth of `path`."""

    instances: list[object] = [None]
    for depth in range(1, len(path) + 1):
        for missing in (False, True):
            instance: object = "x"
            for index in range(depth, 0, -1):
                key = path[index - 1]
                if index == depth:
                    instance = {} if missing else {key: None}
                else:
                    instance = {key: instance}
            instances.append(instance)
    return instances


def _path_contract(
    path: tuple[str, ...], leaf: dict, *, above: dict | None = None
) -> dict:
    contract = leaf
    for key in reversed(path):
        contract = {
            "type": "object",
            "properties": {key: contract},
            "required": [key],
            **(above or {}),
        }
    return contract


# Extra keywords on every object above the field, and on the field itself.
_EXTRA_ABOVE = [
    {},
    {"additionalProperties": False, "title": "T", "description": "D"},
    {"allOf": [{"not": {"required": ["secret"]}}], "minProperties": 1},
    {"anyOf": [{"required": ["x"]}, {}], "enum": [{"x": {"x": "a"}}, {"a": {}}]},
]
_EXTRA_LEAF = [
    {},
    {"title": "T", "description": "D"},
    {"minLength": 1, "pattern": "^a", "enum": ["a", "ab"]},
    {"allOf": [{"minLength": 1}], "anyOf": [{"pattern": "^a"}, {}], "const": "a"},
    {"minimum": 0, "maximum": 9, "multipleOf": 1},
]


@pytest.mark.parametrize("path", [("x",), ("a", "x"), ("a", "b", "x")])
@pytest.mark.parametrize("leaf_type", ["string", "number", "integer", "boolean"])
@pytest.mark.parametrize("extra_leaf", _EXTRA_LEAF)
@pytest.mark.parametrize("extra_above", _EXTRA_ABOVE)
def test_the_accepted_shape_admits_no_null_and_no_missing_field(
    path: tuple[str, ...], leaf_type: str, extra_leaf: dict, extra_above: dict
) -> None:
    contract = _path_contract(
        path, {"type": leaf_type, **extra_leaf}, above=extra_above
    )

    assert template_bound_path_ok(contract, path)
    validator = jsonschema.Draft202012Validator(contract)
    for instance in _null_instances(path):
        assert not validator.is_valid(instance), instance


_ANNOTATIONS = {
    "title": "T",
    "description": "D",
    "examples": ["a"],
    "default": "a",
    "$comment": "c",
}


@pytest.mark.parametrize(
    "declared",
    [
        {"type": ["string", "null"]},
        {"type": ["null", "string"]},
        {"type": ["string"]},
        {"type": ["integer", "null"], **_ANNOTATIONS},
        {"type": ["number", "null"], "title": "T"},
        {"type": ["boolean", "null"]},
    ],
)
@pytest.mark.parametrize("above", ["typed", "nullable", "optional", "no-required"])
def test_the_path_made_ok_is_ok_and_admits_no_null(declared: dict, above: str) -> None:
    details: dict = {
        "type": ["object", "null"] if above == "nullable" else "object",
        "properties": {"title": declared, "other": {"type": "string"}},
        "required": [] if above == "optional" else ["title"],
        "description": "Details",
    }
    if above == "no-required":
        del details["required"]
    contract = {
        "type": ["object", "null"],
        "properties": {"details": details},
        "additionalProperties": False,
    }
    path = ("details", "title")

    made = template_bound_path_made_ok(contract, path)

    assert made is not None
    assert template_bound_path_ok(made, path)
    validator = jsonschema.Draft202012Validator(made)
    for instance in _null_instances(path):
        assert not validator.is_valid(instance), instance


def test_the_path_made_ok_touches_only_type_and_required_of_plain_nodes() -> None:
    contract = {
        "type": ["object", "null"],
        "properties": {
            "details": {
                "type": ["object", "null"],
                "description": "Details",
                "examples": [{"count": 1}],
                "properties": {
                    "count": {
                        "type": ["integer", "null"],
                        **_ANNOTATIONS,
                    },
                    "other": {"type": ["string", "null"]},
                },
                "required": ["other"],
            },
            "unrelated": {"type": ["string", "null"], "default": None},
        },
        "additionalProperties": False,
    }

    made = template_bound_path_made_ok(contract, ("details", "count"))

    assert made == {
        "type": "object",
        "properties": {
            "details": {
                "type": "object",
                "description": "Details",
                "examples": [{"count": 1}],
                "properties": {
                    "count": {"type": "integer", **_ANNOTATIONS},
                    "other": {"type": ["string", "null"]},
                },
                "required": ["other", "count"],
            },
            "unrelated": {"type": ["string", "null"], "default": None},
        },
        "additionalProperties": False,
        "required": ["details"],
    }
    # The input is not modified.
    assert contract["properties"]["details"]["type"] == ["object", "null"]


def test_the_path_made_ok_leaves_a_node_that_is_already_ok_whatever_it_carries() -> (
    None
):
    guard = {"allOf": [{"not": {"required": ["secret"]}}], "minProperties": 1}
    contract = {
        "type": "object",
        **guard,
        "properties": {
            "details": {
                "type": "object",
                **guard,
                "properties": {
                    "count": {"type": "integer", "minimum": 0, "enum": [0, 1, None]}
                },
                "required": ["count"],
            }
        },
        "required": ["details"],
    }

    assert template_bound_path_made_ok(contract, ("details", "count")) == contract


# Keywords a node may carry without being touched only when it needs no change:
# each can make the schema unsatisfiable or change what a null means once the
# node is edited.
_ASSERTING_KEYWORDS = {
    "not": {"required": ["title"]},
    "if": {"required": ["other"]},
    "then": {"required": ["other"]},
    "else": {"required": ["other"]},
    "allOf": [{"minProperties": 1}],
    "anyOf": [{"required": ["other"]}, {}],
    "oneOf": [{"required": ["other"]}],
    "enum": [None],
    "const": None,
    "dependentRequired": {"title": ["other"]},
    "dependentSchemas": {"title": {"required": ["other"]}},
    "maxProperties": 1,
    "minProperties": 1,
    "propertyNames": {"maxLength": 1},
    "patternProperties": {"^t": {"type": "string"}},
    "unevaluatedProperties": False,
    "minLength": 1,
    "minimum": 0,
    "pattern": "^a",
    "format": "date",
    "contains": {"type": "string"},
    "$ref": "#/$defs/x",
    "deprecated": True,
}


@pytest.mark.parametrize("keyword", sorted(_ASSERTING_KEYWORDS))
@pytest.mark.parametrize("needs", ["required", "type-list"])
def test_the_path_made_ok_does_not_edit_an_ancestor_that_carries_an_asserting_keyword(
    keyword: str, needs: str
) -> None:
    # Adding `title` to `required` under {"not": {"required": ["title"]}} makes
    # every output invalid; an ancestor that asserts anything is not edited.
    details: dict = {
        "type": "object" if needs == "required" else ["object", "null"],
        "properties": {"title": {"type": "string"}, "other": {"type": "string"}},
        "required": [] if needs == "required" else ["title"],
        keyword: _ASSERTING_KEYWORDS[keyword],
    }
    contract = {
        "type": "object",
        "properties": {"details": details},
        "required": ["details"],
    }

    assert template_bound_path_made_ok(contract, ("details", "title")) is None


@pytest.mark.parametrize("keyword", sorted(_ASSERTING_KEYWORDS))
def test_the_path_made_ok_does_not_edit_a_field_that_carries_an_asserting_keyword(
    keyword: str,
) -> None:
    # {"type": ["string", "null"], "enum": [null]} would become
    # {"type": "string", "enum": [null]}, which no value satisfies.
    leaf = {"type": ["string", "null"], keyword: _ASSERTING_KEYWORDS[keyword]}

    assert template_bound_path_made_ok(_nested(leaf), ("details", "title")) is None


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("additionalProperties", False),
        ("items", {"type": "string"}),
        ("title", "T"),
        ("description", "D"),
        ("examples", ["a"]),
        ("default", "a"),
        ("$comment", "c"),
    ],
)
def test_the_path_made_ok_edits_a_node_that_carries_only_plain_keywords(
    keyword: str, value: object
) -> None:
    # `default` and `examples` are annotations in draft 2020-12: they assert
    # nothing, so narrowing beside them cannot leave a schema no value satisfies.
    contract = _nested(
        {"type": ["string", "null"], keyword: value},
        above={"type": ["object", "null"], "required": [], keyword: value},
    )

    made = template_bound_path_made_ok(contract, ("details", "title"))

    assert made is not None
    assert template_bound_path_ok(made, ("details", "title"))
    details = made["properties"]["details"]
    assert details[keyword] == value
    assert details["properties"]["title"] == {"type": "string", keyword: value}


def test_the_path_made_ok_refuses_both_inputs_that_narrowing_would_make_unsatisfiable() -> (
    None
):
    enum_null = _nested({"type": ["string", "null"], "enum": [None]})
    forbids_title = _nested(
        {"type": "string"},
        above={"not": {"required": ["title"]}, "required": []},
    )

    assert template_bound_path_made_ok(enum_null, ("details", "title")) is None
    assert template_bound_path_made_ok(forbids_title, ("details", "title")) is None


def _own(node: dict) -> dict:
    return {key: value for key, value in node.items() if key != "properties"}


def _path_nodes(contract: dict) -> list[dict]:
    details = contract["properties"]["details"]
    return [contract, details, details["properties"]["title"]]


# Where a keyword that asserts something can sit relative to the edited path.
_LOCATIONS = ("root", "details", "title", "sibling", "unrelated", "defs")


def _shape(
    ancestor_type: object,
    requirement: str,
    leaf_type: object,
    location: str | None,
    extra: dict,
) -> dict:
    title: dict = {} if leaf_type is None else {"type": leaf_type}
    details: dict = {
        "properties": {"title": title, "other": {"type": "string"}},
        "additionalProperties": False,
    }
    if ancestor_type is not None:
        details["type"] = ancestor_type
    if requirement != "absent":
        details["required"] = ["title"] if requirement == "listed" else []
    contract: dict = {
        "type": "object",
        "properties": {
            "details": details,
            "unrelated": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["details", "unrelated"],
        "additionalProperties": False,
    }
    if location == "root":
        contract.update(extra)
    elif location == "details":
        details.update(extra)
    elif location == "title":
        title.update(extra)
    elif location == "sibling":
        details["properties"]["other"].update(extra)
    elif location == "unrelated":
        contract["properties"]["unrelated"].update(extra)
    elif location == "defs":
        contract["$defs"] = {"alias": {"$ref": "#/properties/details/properties/title"}}
        contract["properties"]["alias"] = {"$ref": "#/$defs/alias", **extra}
    return contract


_ROUND_SIX = {"required": ["details", "phantom"], "additionalProperties": False}
# Plain: a required key the properties do not declare, typed by an open schema.
_OPEN_REQUIRED = {
    "required": ["details", "unrelated", "extra"],
    "additionalProperties": {"type": "integer"},
}


def _generated_contracts() -> Iterator[dict]:
    """Contracts with an asserting keyword or a closed object that requires an
    undeclared key at the root, the objects, the field, a sibling, another
    branch or `$defs`, in every combination of type and requiredness."""

    extras = [
        {"description": "D"},
        {"items": False},
        _OPEN_REQUIRED,
        *({k: v} for k, v in _ASSERTING_KEYWORDS.items()),
        _ROUND_SIX,
    ]
    leaf_types = [
        "string",
        ["string", "null"],
        "integer",
        ["integer", "null"],
        "array",
        None,
        ["string", "integer"],
        "null",
    ]
    yield from (
        _shape(a, r, leaf, None, {})
        for a, r, leaf in itertools.product(
            ["object", ["object", "null"], ["object"], None],
            ["listed", "unlisted", "absent"],
            leaf_types,
        )
    )
    yield from (
        _shape(a, r, leaf, location, extra)
        for a, r, leaf, location, extra in itertools.product(
            ["object", ["object", "null"]],
            ["listed", "unlisted", "absent"],
            leaf_types,
            _LOCATIONS,
            extras,
        )
    )


def test_the_plain_check_agrees_with_an_independent_oracle_on_every_generated_shape() -> (
    None
):
    plain = 0
    for contract in _generated_contracts():
        assert _is_plain_tree(contract) == all_plain(contract), contract
        plain += all_plain(contract)
    assert plain > 100


def test_the_path_made_ok_edits_only_an_entirely_plain_schema_and_the_result_is_satisfiable() -> (
    None
):
    # Whatever sits next to the path, above it or in another branch: when the
    # compiler edits, the whole input was plain, only type and required moved,
    # and the result still accepts an instance. When anything asserts, it does
    # not edit at all.
    path = ("details", "title")
    shapes = _generated_contracts()
    changed = refused = 0
    for contract in shapes:
        made = template_bound_path_made_ok(contract, path)

        if made is None:
            refused += 1
            assert not template_bound_path_ok(contract, path)
            continue
        if made == contract:
            continue
        changed += 1
        assert all_plain(contract), contract
        assert template_bound_path_ok(made, path)
        assert jsonschema.Draft202012Validator(made).is_valid(witness(made)), made
        for before, after in zip(_path_nodes(contract), _path_nodes(made), strict=True):
            moved = {
                key
                for key in set(_own(before)) | set(_own(after))
                if _own(before).get(key) != _own(after).get(key)
            }
            assert moved <= {"type", "required"}, (before, after)
        assert (
            made["properties"]["details"]["properties"]["other"]
            == (contract["properties"]["details"]["properties"]["other"])
        )
        assert made["properties"]["unrelated"] == contract["properties"]["unrelated"]
    assert changed > 100
    assert refused > 1000


@pytest.mark.parametrize("location", _LOCATIONS)
@pytest.mark.parametrize("keyword", sorted(_ASSERTING_KEYWORDS))
def test_the_path_made_ok_edits_nothing_when_any_node_of_the_schema_asserts(
    keyword: str, location: str
) -> None:
    # The path needs an edit (optional field, nullable field), and something else
    # in the schema asserts: nothing is changed and the caller is told.
    contract = _shape(
        ["object", "null"],
        "unlisted",
        ["string", "null"],
        location,
        {keyword: _ASSERTING_KEYWORDS[keyword]},
    )

    assert template_bound_path_made_ok(contract, ("details", "title")) is None


# A closed object that requires a key it does not declare has no instance.
_PHANTOM = {
    "type": "object",
    "properties": {"x": {"type": "string"}},
    "required": ["x", "phantom"],
    "additionalProperties": False,
}


def test_the_path_made_ok_repairs_a_contract_with_a_closed_array_of_no_items() -> None:
    # `items: false` accepts only the empty array: the witness is [], not one item.
    contract = {
        "type": "object",
        "properties": {
            "title": {"type": ["string", "null"]},
            "rows": {"type": "array", "items": False},
        },
        "required": ["rows"],
        "additionalProperties": False,
    }

    made = template_bound_path_made_ok(contract, ("title",))

    assert made is not None
    assert made["properties"]["title"] == {"type": "string"}
    assert made["required"] == ["rows", "title"]
    assert made["properties"]["rows"] == contract["properties"]["rows"]


def test_the_path_made_ok_repairs_a_contract_whose_required_extra_key_is_typed_by_additional() -> (
    None
):
    # `extra` is required but only additionalProperties types it: the witness
    # takes its value from that schema (0), not "".
    contract = {
        "type": "object",
        "properties": {"title": {"type": ["string", "null"]}},
        "required": ["extra"],
        "additionalProperties": {"type": "integer"},
    }

    made = template_bound_path_made_ok(contract, ("title",))

    assert made is not None
    assert made["properties"]["title"] == {"type": "string"}
    assert made["required"] == ["extra", "title"]
    assert made["additionalProperties"] == {"type": "integer"}
    assert jsonschema.Draft202012Validator(made).is_valid({"extra": 0, "title": ""})


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.parametrize("where", ["field", "sibling", "defs", "items"])
def test_a_remote_ref_is_never_resolved_by_publish_or_the_compiler(
    keyword: str, where: str
) -> None:
    # jsonschema fetches a remote $ref when it validates. Neither the contract
    # check, the publish remedy nor the witness check may fetch one, so a real
    # listener sees no request at all.
    path = ("details", "title")
    with local_listener() as (base, requested):
        ref = {keyword: f"{base}/x"}
        leaf: dict = {"type": "string", **(ref if where == "field" else {})}
        contract = _nested(leaf, above={"required": []})
        if where == "sibling":
            contract["properties"]["details"]["properties"]["other"] = ref
        elif where == "defs":
            contract["$defs"] = {"remote": ref}
        elif where == "items":
            contract["properties"]["rows"] = {"type": "array", "items": ref}

        steps = _template_fill_over_contract(
            contract, binding="{{step_1.output.structured.details.title}}"
        )
        with pytest.raises(FlowStepValidationError) as exc_info:
            validate_steps(steps, require_complete_template_fill_config=True)
        issues = collect_step_graph_issues(
            flow_step_validation_views_from_flow_steps(steps),
            require_complete_template_fill_config=True,
        )
        made = template_bound_path_made_ok(contract, path)

    # The contract owner refuses the reference first, once, with its own code. The
    # publish advice, which follows the leaf's type alone, is a second fact about
    # the same flow and still runs without a validator.
    assert exc_info.value.code == "invalid_output_contract_schema"
    assert exc_info.value.step_order == 1
    assert keyword in str(exc_info.value)
    assert [issue.code.value for issue in issues].count(
        "invalid_output_contract_schema"
    ) == 1
    assert any("only if the field accepts one" in issue.message for issue in issues)
    assert made is None
    assert requested == []


def test_data_that_only_looks_like_a_ref_is_not_one_and_the_contract_is_repaired() -> (
    None
):
    # A property NAMED "$ref" is a name under `properties`, and `default` and
    # `examples` hold data: none is a keyword, so the tree is plain and the
    # validator never resolves any of them, whatever URL they carry.
    with local_listener() as (base, requested):
        data = {"$ref": f"{base}/x", "$dynamicRef": f"{base}/y"}
        contract = {
            "type": "object",
            "properties": {
                "$ref": {"type": "string", "default": data, "examples": [data]},
                "title": {
                    "type": ["string", "null"],
                    "default": data,
                    "examples": [{"$dynamicRef": f"{base}/z"}, data],
                },
            },
            "required": ["$ref"],
            "additionalProperties": False,
        }

        assert _is_plain_tree(contract)
        made = template_bound_path_made_ok(contract, ("title",))

    assert made is not None
    assert made["properties"]["title"]["type"] == "string"
    assert made["required"] == ["$ref", "title"]
    assert template_bound_path_ok(made, ("title",))
    assert requested == []


def test_the_path_made_ok_refuses_the_round_six_input() -> None:
    contract = {
        "type": ["object", "null"],
        "properties": {"title": {"type": "string"}},
        "required": ["title", "phantom"],
        "additionalProperties": False,
    }

    assert template_bound_path_made_ok(contract, ("title",)) is None


@pytest.mark.parametrize(
    "placement", ["root", "details", "sibling", "unrelated", "array-item", "field"]
)
@pytest.mark.parametrize(
    "needs", ["nullable-object", "optional-field", "nullable-field"]
)
def test_the_path_made_ok_never_edits_a_schema_with_a_required_undeclared_key_under_closed(
    placement: str, needs: str
) -> None:
    details: dict = {
        "type": ["object", "null"] if needs == "nullable-object" else "object",
        "properties": {
            "title": {
                "type": ["string", "null"] if needs == "nullable-field" else "string"
            },
            "other": {"type": "string"},
        },
        "required": [] if needs == "optional-field" else ["title"],
    }
    contract: dict = {
        "type": "object",
        "properties": {
            "details": details,
            "unrelated": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["details"],
    }
    if placement == "root":
        contract.update(required=["details", "phantom"], additionalProperties=False)
    elif placement == "details":
        details.update(
            required=[*details["required"], "phantom"], additionalProperties=False
        )
    elif placement == "sibling":
        details["properties"]["other"] = _PHANTOM
    elif placement == "unrelated":
        contract["properties"]["unrelated"] = _PHANTOM
    elif placement == "array-item":
        contract["properties"]["unrelated"]["items"] = _PHANTOM
    else:
        details["properties"]["title"]["additionalProperties"] = False
        details["properties"]["title"]["required"] = ["phantom"]

    assert not all_plain(contract)
    assert template_bound_path_made_ok(contract, ("details", "title")) is None


@pytest.mark.parametrize(
    "sibling",
    [
        {"type": "strng"},
        {"type": ["string", "string"]},
        {"type": []},
        {"type": "object", "required": "x"},
    ],
)
def test_the_path_made_ok_refuses_a_contract_the_platform_validator_cannot_use(
    sibling: dict,
) -> None:
    # Plain by keyword, but no draft 2020-12 validator can evaluate it: the
    # final-artifact witness check refuses rather than editing or raising.
    contract = _shape(["object", "null"], "unlisted", ["string", "null"], None, {})
    contract["properties"]["details"]["properties"]["other"] = sibling

    assert template_bound_path_made_ok(contract, ("details", "title")) is None


def test_the_path_made_ok_refuses_the_inputs_an_interacting_assertion_would_break() -> (
    None
):
    path = ("details", "title")
    guard = {"allOf": [{"properties": {"title": {"const": None}}}]}
    ancestor_const_null = _shape(
        ["object", "null"], "unlisted", ["string", "null"], "details", guard
    )
    newly_required_enum_null = _nested(
        {"type": "string", "enum": [None]}, above={"required": []}
    )
    sibling_ref_const_null = _shape(
        "object", "listed", ["string", "null"], "defs", {"const": None}
    )

    for contract in (
        ancestor_const_null,
        newly_required_enum_null,
        sibling_ref_const_null,
    ):
        assert template_bound_path_made_ok(contract, path) is None


@pytest.mark.parametrize(
    ("leaf", "wording"),
    [
        # A string gets the conditional advice: "" only if the field accepts one.
        ({"type": "string"}, "only if the field accepts one"),
        ({"type": ["string", "null"]}, "only if the field accepts one"),
        ({"type": "string", "minLength": 1}, "only if the field accepts one"),
        ({"type": "string", "enum": ["a", "b"]}, "only if the field accepts one"),
        ({"type": "string", "$ref": "#/$defs/t"}, "only if the field accepts one"),
        # A number, integer or boolean has no empty value at all.
        ({"type": "number"}, "always gives a valid value"),
        ({"type": "integer"}, "always gives a valid value"),
        ({"type": "boolean"}, "always gives a valid value"),
        ({"type": ["integer", "null"]}, "always gives a valid value"),
    ],
)
def test_the_publish_remedy_for_a_missing_value_fits_the_type_of_the_field(
    leaf: dict, wording: str
) -> None:
    # The advice follows the field's type alone, with no validator call: a
    # string may take an empty string only if it accepts one; a number, integer
    # or boolean is given a valid value, and a deliberately blank template
    # binding is how the placeholder stays empty.
    steps = _template_fill_over_contract(
        {**_nested(leaf, above={"required": []}), **_LOCAL_TARGETS},
        binding="{{step_1.output.structured.details.title}}",
    )

    with pytest.raises(FlowStepValidationError) as exc_info:
        validate_steps(steps, require_complete_template_fill_config=True)

    message = str(exc_info.value)
    assert wording in message
    assert "blank template binding" in message
    if wording == "always gives a valid value":
        assert "empty string" not in message


@pytest.mark.parametrize(
    "leaf",
    [
        p
        for p in _UNPLAIN_LEAVES
        if p.id
        not in {"type-list-with-null", "type-list-null-first", "type-list-of-one"}
    ],
)
def test_the_path_made_ok_has_no_answer_for_a_field_without_a_type_it_can_keep(
    leaf: dict,
) -> None:
    assert template_bound_path_made_ok(_nested(leaf), ("details", "title")) is None


@pytest.mark.parametrize(
    "above",
    [{"type": ["object", "string"]}, {"$ref": "#/$defs/details"}, {"type": "array"}],
)
def test_the_path_made_ok_has_no_answer_for_an_object_it_cannot_make_one_type(
    above: dict,
) -> None:
    contract = _nested({"type": "string"}, above=above)

    assert template_bound_path_made_ok(contract, ("details", "title")) is None


@pytest.mark.parametrize(
    "leaf",
    [
        {"type": "array", "items": {"type": "string"}},
        {"type": "object", "properties": {"a": {"type": "string"}}},
    ],
)
def test_the_path_made_ok_leaves_a_container_for_publication_to_name(
    leaf: dict,
) -> None:
    contract = _nested(leaf)

    assert template_bound_path_made_ok(contract, ("details", "title")) is contract
    assert not template_bound_path_ok(contract, ("details", "title"))


def test_the_path_made_ok_leaves_a_path_the_contract_does_not_have_as_it_is() -> None:
    contract = _nested({"type": ["string", "null"]})

    assert template_bound_path_made_ok(contract, ("details", "missing")) is contract
    assert template_bound_path_made_ok(contract, ("other", "title")) is contract


@pytest.mark.parametrize(
    "schema",
    [
        {"enum": ["text", {"title": "object"}]},
        {"const": ["array"]},
        {"anyOf": [{"type": "string"}, {"type": "object"}]},
        {"oneOf": [{"type": "number"}, {}]},
    ],
)
def test_template_fill_publish_rejects_schemas_that_allow_containers(schema) -> None:
    with pytest.raises(FlowStepValidationError, match="scalar"):
        validate_steps(
            [
                _step(
                    output_contract={"type": "object", "properties": {"value": schema}}
                ),
                _step(
                    step_order=2,
                    output_type="docx",
                    output_mode="template_fill",
                    output_config={
                        "template_asset_id": str(uuid4()),
                        "bindings": {"body": "{{step_1.output.structured.value}}"},
                    },
                ),
            ],
            require_complete_template_fill_config=True,
        )


def test_validate_steps_rejects_inline_citation_mode_for_non_text_output() -> None:
    steps = [
        _step(
            output_type="json",
            output_config={"citation_mode": "inline_inref_sidecar"},
        )
    ]
    _assert_validate_steps_rejects(
        steps,
        expected_type=FlowStepValidationError,
        match="citation_mode 'inline_inref_sidecar' requires output_type 'text'",
        step_order=1,
    )
    assert [issue.code for issue in collect_step_graph_issues(steps)] == [
        FlowGraphIssueCode.CITATION_MODE_UNSUPPORTED
    ]


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


def test_mapped_per_item_step_rejects_explicit_underlag() -> None:
    array_contract = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "object"}}},
    }
    step = _step(
        2,
        input_type="json",
        input_contract=array_contract,
        output_contract=array_contract,
        input_config={"item_map": {"enabled": True, "max_items": 3}},
        input_bindings={
            "source_refs": [{"step_ref": "step_1", "output": "structured"}]
        },
    )

    with pytest.raises(FlowStepValidationError, match="explicit input_bindings"):
        _validate_step_mapped_execution(
            step=flow_step_validation_view_from_flow_step(step)
        )


@pytest.mark.parametrize("publish_strict", [False, True])
@pytest.mark.parametrize(
    "bindings",
    [
        {"question": "{{step_1}}"},
        {"question": "{{step_2.output.structured.title}}"},
        {"question": "{{step_2.output.structured.items}}"},
        {"source_refs": [{"step_ref": "step_1", "output": "text"}]},
        # The shape the editor's repair produces for a source ref: a scalar
        # field, never an array (arrays need an item template it cannot author).
        {
            "source_refs": [
                {"step_ref": "step_2", "output": "structured", "field_path": "title"}
            ]
        },
    ],
)
def test_validate_steps_accepts_reference_repair_fixtures(
    bindings: dict, publish_strict: bool
) -> None:
    validate_steps(
        [
            _step(1, output_type="text"),
            _step(
                2,
                output_contract={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                            },
                        },
                    },
                },
            ),
            _step(
                3,
                input_bindings=bindings,
                output_mode="compose_text",
                output_type="text",
            ),
        ],
        require_complete_template_fill_config=publish_strict,
    )


_SECTION_RECORDS = {
    "type": "object",
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["records"],
    "additionalProperties": False,
}


def _sectioned(step_order: int, **updates) -> FlowStep:
    return _step(
        step_order,
        input_config={"text_processing": {"mode": "process_each_section"}},
        output_contract=_SECTION_RECORDS,
        **updates,
    )


def _transcript(step_order: int = 1) -> FlowStep:
    return _step(
        step_order,
        input_type="audio",
        output_mode="transcribe_only",
        output_type="text",
    )


def _speaker_mapping(step_order: int) -> FlowStep:
    return _step(
        step_order,
        output_mode="speaker_mapping",
        output_config={"speaker_mapping": {"infer_names": True}},
        review_policy=FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT),
    )


def _question(template: str) -> dict:
    return {"input_bindings": {"question": template}}


@pytest.mark.parametrize(
    ("steps", "field", "reference", "source_step_order"),
    [
        pytest.param(
            [_step(1), _sectioned(2, **_question("{{ step_1.output.text }}"))],
            "input_bindings.question",
            "step_1.output.text",
            1,
            id="json-step-text",
        ),
        pytest.param(
            [_step(1), _sectioned(2)],
            "input_source",
            "previous_step",
            1,
            id="implicit-previous-json-step",
        ),
        pytest.param(
            [_step(1), _sectioned(2, **_question("{{ föregående_steg }}"))],
            "input_bindings.question",
            "föregående_steg",
            1,
            id="previous-step-alias",
        ),
        pytest.param(
            [
                _step(1),
                _sectioned(
                    2,
                    input_bindings={
                        "source_refs": [{"step_ref": "step_1", "output": "text"}]
                    },
                ),
            ],
            "input_bindings.source_refs[0].step_ref",
            "step_1",
            1,
            id="source-ref",
        ),
        pytest.param(
            [
                _transcript(1),
                _speaker_mapping(2),
                _sectioned(3, **_question("{{ step_2.output.text }}")),
            ],
            "input_bindings.question",
            "step_2.output.text",
            2,
            id="speaker-mapped-transcript",
        ),
    ],
)
def test_publish_refuses_section_step_reading_structured_output(
    steps: list[FlowStep], field: str, reference: str, source_step_order: int
) -> None:
    section_step_order = steps[-1].step_order
    exc = _assert_validate_steps_rejects(
        steps,
        expected_type=FlowStepValidationError,
        match=f"step {source_step_order}",
        code=FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        step_order=section_step_order,
        metadata_json=_audio_metadata(),
        require_complete_template_fill_config=True,
    )
    assert reference in str(exc)
    assert exc.context is not None
    assert exc.context["field"] == field
    assert exc.context["reference"] == reference
    assert exc.context["source_step_order"] == source_step_order


@pytest.mark.parametrize(
    ("prompt", "reference"),
    [
        pytest.param(
            "Notera {{ step_1.output.text }}", "step_1.output.text", id="step"
        ),
        pytest.param("Notera {{ föregående_steg }}", "föregående_steg", id="alias"),
    ],
)
def test_publish_refuses_section_step_whose_prompt_reads_structured_output(
    prompt: str, reference: str
) -> None:
    # The question reads text; the assistant prompt selects the JSON step too.
    steps = [
        _step(1),
        _sectioned(2, **_question("{{ flow_input.text }}")),
    ]

    with pytest.raises(FlowStepValidationError) as caught:
        validate_steps(
            steps,
            metadata_json=_audio_metadata(),
            require_complete_template_fill_config=True,
            prompt_templates={2: prompt},
        )

    assert caught.value.code == (
        FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    assert caught.value.step_order == 2
    assert caught.value.context is not None
    assert caught.value.context["field"] == "prompt"
    assert caught.value.context["reference"] == reference
    assert caught.value.context["source_step_order"] == 1


def test_publish_accepts_section_step_whose_prompt_reads_text() -> None:
    validate_steps(
        [
            _step(1),
            _step(2, output_type="text"),
            _sectioned(3, **_question("{{ step_2.output.text }}")),
        ],
        metadata_json=_audio_metadata(),
        require_complete_template_fill_config=True,
        prompt_templates={
            1: "{{ flow_input.text }}",
            3: "Kontext: {{ föregående_steg }}",
        },
    )


def test_draft_save_keeps_section_step_reading_structured_output() -> None:
    # Reference-path checks are publish rules; drafts stay saveable mid-edit.
    validate_steps([_step(1), _sectioned(2, **_question("{{ step_1.output.text }}"))])


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [
                _step(1, output_type="text"),
                _sectioned(2, **_question("{{ step_1.output.text }}")),
            ],
            id="section-reads-text-step",
        ),
        pytest.param(
            [_step(1, output_type="text"), _sectioned(2)],
            id="section-reads-implicit-text-step",
        ),
        pytest.param(
            [_transcript(1), _sectioned(2, **_question("{{ step_1.output.text }}"))],
            id="section-reads-transcript",
        ),
        pytest.param(
            [
                _step(1),
                _step(2, output_type="text"),
                _sectioned(3, **_question("{{ step_2.output.text }}")),
            ],
            id="section-reads-text-after-json-step",
        ),
        pytest.param(
            [
                _step(
                    1,
                    output_contract={
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                    },
                ),
                _step(
                    2,
                    output_type="text",
                    **_question(
                        "{{ step_1.output.structured.title }} {{ step_1.output.text }}"
                    ),
                ),
            ],
            id="json-step-field-and-text",
        ),
        pytest.param(
            [
                _step(1, output_type="text"),
                _sectioned(2),
                _step(3, **_question("{{ step_2.output.structured.records }}")),
            ],
            id="section-output-records",
        ),
    ],
)
def test_publish_accepts_reads_the_source_step_produces(steps: list[FlowStep]) -> None:
    validate_steps(
        steps,
        metadata_json=_audio_metadata(),
        require_complete_template_fill_config=True,
    )
