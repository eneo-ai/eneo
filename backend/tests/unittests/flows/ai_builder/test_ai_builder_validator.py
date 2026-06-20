"""Tests for AI Builder spec validation — hard validation + quality lint."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_domain_models import (
    LintSeverity,
)
from intric.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationError,
    SpecValidationResult,
)
from intric.flows.ai_builder.ai_builder_validator import (
    _BUILDER_IGNORED_FLOW_VALIDATION_CODES,
    _CANONICAL_GRAPH_CODE_TO_BUILDER_CODE,
    _CANONICAL_GRAPH_CODES_WITH_GENERIC_BUILDER_PRESENTATION,
    validate_spec,
)
from intric.flows.domain.flow_step_validation import FlowGraphIssueCode
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step(
    ref: str = "step_a",
    name: str = "Test step",
    instructions: str = "Do something useful",
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    **kwargs: object,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        **kwargs,  # type: ignore[arg-type]
    )


def _spec(steps: list[StepSpec], flow_name: str = "Test") -> FlowDraftSpecCore:
    return FlowDraftSpecCore(flow_name=flow_name, steps=steps)


def _errors_with_code(
    result: SpecValidationResult, code: str
) -> list[SpecValidationError]:
    return [error for error in result.errors if error.code == code]


def _assert_single_error(
    result: SpecValidationResult, *, code: str, step_ref: str | None
) -> None:
    errors = _errors_with_code(result, code)
    assert len(errors) == 1
    assert errors[0].step_ref == step_ref


class TestCanonicalGraphIssuePresentation:
    def test_every_canonical_graph_issue_has_builder_presentation(self) -> None:
        presented_codes = (
            set(_CANONICAL_GRAPH_CODE_TO_BUILDER_CODE)
            | set(_CANONICAL_GRAPH_CODES_WITH_GENERIC_BUILDER_PRESENTATION)
            | set(_BUILDER_IGNORED_FLOW_VALIDATION_CODES)
        )

        assert set(FlowGraphIssueCode) <= presented_codes


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidSpec:
    def test_single_step_valid(self) -> None:
        result = validate_spec(_spec([_step()]))
        assert result.valid

    def test_two_step_chain_valid(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Extract"),
                    _step(
                        ref="step_b",
                        name="Summarize",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ]
            )
        )
        assert result.valid

    def test_three_step_chain_valid(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract",
                        input_source=InputSource.FLOW_INPUT,
                    ),
                    _step(
                        ref="step_b",
                        name="Analyze",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                    _step(
                        ref="step_c",
                        name="Summarize",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                    ),
                ]
            )
        )
        assert result.valid

    def test_audio_transcription_chain_valid(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transkribera",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Sammanfatta",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ]
            )
        )
        assert result.valid

    def test_json_output_chain_valid(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Extract", output_type=OutputType.JSON),
                    _step(
                        ref="step_b",
                        name="Parse",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                    ),
                ]
            )
        )
        assert result.valid

    def test_terminal_json_output_without_contract_stays_valid_without_warning(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Return structured payload",
                        output_type=OutputType.JSON,
                    )
                ]
            )
        )
        assert result.valid
        assert not any(w.code == "json_output_no_contract" for w in result.warnings)


# ---------------------------------------------------------------------------
# Empty steps
# ---------------------------------------------------------------------------


class TestEmptySteps:
    def test_empty_steps_rejected(self) -> None:
        result = validate_spec(_spec([]))
        assert not result.valid
        assert result.errors[0].code == "empty_steps"


# ---------------------------------------------------------------------------
# Duplicate refs / names
# ---------------------------------------------------------------------------


class TestDuplicates:
    def test_duplicate_step_ref_rejected(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_a",
                        name="Second",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "duplicate_step_ref" for e in result.errors)

    def test_duplicate_step_name_rejected(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Same Name"),
                    _step(
                        ref="step_b",
                        name="same name",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "duplicate_step_name" for e in result.errors)
        _assert_single_error(result, code="duplicate_step_name", step_ref="step_b")

    def test_empty_step_name_rejected(self) -> None:
        result = validate_spec(_spec([_step(name="   ")]))
        assert not result.valid
        assert any(e.code == "empty_step_name" for e in result.errors)


# ---------------------------------------------------------------------------
# Chaining rules
# ---------------------------------------------------------------------------


class TestChainingRules:
    def test_first_step_cannot_use_previous_step(self) -> None:
        result = validate_spec(_spec([_step(input_source=InputSource.PREVIOUS_STEP)]))
        assert not result.valid
        assert any(e.code == "first_step_invalid_source" for e in result.errors)
        _assert_single_error(
            result, code="first_step_invalid_source", step_ref="step_a"
        )

    def test_first_step_cannot_use_all_previous_steps(self) -> None:
        result = validate_spec(
            _spec([_step(input_source=InputSource.ALL_PREVIOUS_STEPS)])
        )
        assert not result.valid
        assert any(e.code == "first_step_invalid_source" for e in result.errors)

    def test_only_one_flow_input_step(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a", name="First", input_source=InputSource.FLOW_INPUT
                    ),
                    _step(
                        ref="step_b", name="Second", input_source=InputSource.FLOW_INPUT
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "multiple_flow_input" for e in result.errors)
        _assert_single_error(result, code="multiple_flow_input", step_ref="step_b")

    def test_flow_input_must_be_first(self) -> None:
        # Can't really test this directly since we'd need a step before flow_input
        # that uses previous_step — which would also fail. But the validation checks.
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="First",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                    _step(
                        ref="step_b", name="Second", input_source=InputSource.FLOW_INPUT
                    ),
                ]
            )
        )
        assert not result.valid

    def test_audio_requires_flow_input(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_b",
                        name="Audio",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.AUDIO,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "media_source_mismatch" for e in result.errors)
        _assert_single_error(result, code="media_source_mismatch", step_ref="step_b")

    def test_document_requires_flow_input(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_b",
                        name="Doc",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.DOCUMENT,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "media_source_mismatch" for e in result.errors)
        _assert_single_error(result, code="media_source_mismatch", step_ref="step_b")

    def test_file_requires_flow_input(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_b",
                        name="File",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.FILE,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "media_source_mismatch" for e in result.errors)
        _assert_single_error(result, code="media_source_mismatch", step_ref="step_b")

    def test_json_all_previous_maps_once_to_authored_step(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Collect"),
                    _step(
                        ref="step_b",
                        name="Merge JSON",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                        input_type=InputType.JSON,
                    ),
                ]
            )
        )

        assert not result.valid
        _assert_single_error(
            result, code="json_all_previous_incompatible", step_ref="step_b"
        )


class TestSemanticVariableValidation:
    def test_unknown_variable_reference_rejected(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Use missing variable",
                        instructions="Use {{ MissingField }} in the prompt.",
                    )
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "unknown_variable_reference" for e in result.errors)

    def test_scalar_runtime_variable_nested_access_rejected(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Use invalid datum access",
                        instructions="Year {{ datum.year }}",
                    )
                ]
            )
        )

        assert not result.valid
        assert any(e.code == "invalid_runtime_variable_path" for e in result.errors)

    def test_unknown_step_input_key_rejected_at_plan_time(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Upload",
                        input_bindings={
                            "question": "Data {{ step_input.nonexistent }}"
                        },
                        input_config={"runtime_input": {"enabled": True}},
                    )
                ]
            )
        )

        assert not result.valid
        assert any(e.code == "invalid_runtime_variable_path" for e in result.errors)

    def test_form_field_variable_reference_allowed(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Form flow",
            steps=[
                _step(
                    ref="step_a",
                    name="Use form variable",
                    instructions="Use {{ flow_input.Ärendenummer }} in the summary.",
                )
            ],
            form_fields=[
                FormFieldSpec(
                    name="Ärendenummer",
                    type="text",
                    label="Ärendenummer",
                    required=True,
                )
            ],
        )
        result = validate_spec(spec)
        assert result.valid

    def test_shadowed_form_field_bare_reference_warns(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Form flow",
            steps=[
                _step(
                    ref="step_a",
                    name="Use form variable",
                    instructions="Use {{ datum }} in the summary.",
                )
            ],
            form_fields=[
                FormFieldSpec(
                    name="datum",
                    type="date",
                    label="Datum",
                    required=True,
                )
            ],
        )

        result = validate_spec(spec)

        assert result.valid
        assert any(
            warning.code == "shadowed_form_field_bare_reference"
            for warning in result.warnings
        )

    def test_reserved_runtime_variable_allowed(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Use system variables",
                        instructions="Date {{ datum }} and input {{ flow_input.text }}.",
                    )
                ]
            )
        )
        assert result.valid

    def test_future_step_reference_in_bindings_rejected(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="First",
                        input_bindings={"question": "Use {{ step_2.output.text }}"},
                    ),
                    _step(
                        ref="step_b",
                        name="Second",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "future_step_reference" for e in result.errors)

    def test_declared_step_reference_requires_supported_output_path(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Extract"),
                    _step(
                        ref="step_b",
                        name="Use malformed reference",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={"question": "Use {{ step_a.text }}"},
                    ),
                ]
            )
        )

        assert not result.valid
        assert any(e.code == "invalid_step_reference_path" for e in result.errors)
        assert not any(
            e.code == "flow_step_invalid"
            and "Invalid step reference 'step_a'" in e.message
            for e in result.errors
        )

    def test_declared_step_reference_rejects_bare_output_path_before_runtime_parity(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Extract"),
                    _step(
                        ref="step_b",
                        name="Use ambiguous output",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={"question": "Use {{ step_a.output }}"},
                    ),
                ]
            )
        )

        assert not result.valid
        assert any(e.code == "invalid_step_reference_path" for e in result.errors)
        assert not any(
            e.code == "flow_step_invalid"
            and "Invalid step reference 'step_a'" in e.message
            for e in result.errors
        )

    def test_declared_step_reference_path_is_checked_in_output_config(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Extract"),
                    _step(
                        ref="step_b",
                        name="Render",
                        input_source=InputSource.PREVIOUS_STEP,
                        output_config={"body": "Use {{ step_a.text }}"},
                    ),
                ]
            )
        )

        assert not result.valid
        assert any(e.code == "invalid_step_reference_path" for e in result.errors)
        assert not any(
            e.code == "flow_step_invalid"
            and "Invalid step reference 'step_a'" in e.message
            for e in result.errors
        )

    def test_whole_structured_output_reference_is_rewritten_for_flow_parity(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract JSON",
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string"},
                            },
                        },
                    ),
                    _step(
                        ref="step_b",
                        name="Use structured object",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={
                            "question": "Use {{ step_a.output.structured }}"
                        },
                    ),
                ]
            )
        )

        assert result.valid

    def test_flow_rule_errors_map_to_authored_step_ref_without_message_parsing(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="Extract"),
                    _step(
                        ref="step_b",
                        name="Use future value",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={"question": "Use {{ step_b.output.text }}"},
                    ),
                ]
            )
        )

        assert any(
            error.code == "flow_step_invalid"
            and error.step_ref == "step_b"
            and "earlier steps" in error.message
            for error in result.errors
        )

    def test_structured_access_requires_json_output(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract",
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Use field",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={
                            "question": "Title: {{ step_1.output.structured.title }}"
                        },
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(
            e.code == "structured_access_requires_json_output" for e in result.errors
        )

    def test_missing_output_contract_field_reference_rejected(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract JSON",
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                            },
                        },
                    ),
                    _step(
                        ref="step_b",
                        name="Summarize",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={
                            "question": "{{ step_1.output.structured.summary }}"
                        },
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "unknown_output_contract_field" for e in result.errors)

    def test_structured_access_allows_numeric_array_indexes(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract JSON",
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {
                                "risker": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "rubrik": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    ),
                    _step(
                        ref="step_b",
                        name="Summarize",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={
                            "question": "{{ step_1.output.structured.risker.0.rubrik }}"
                        },
                    ),
                ]
            )
        )
        assert result.valid

    def test_structured_access_keeps_lenient_array_property_fallback_for_runtime_templates(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract JSON",
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {
                                "risker": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "rubrik": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    ),
                    _step(
                        ref="step_b",
                        name="Summarize",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={
                            "question": "{{ step_1.output.structured.risker.rubrik }}"
                        },
                    ),
                ]
            )
        )
        assert result.valid

    def test_structured_access_accepts_fields_from_composite_output_contracts(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract JSON",
                        output_type=OutputType.JSON,
                        output_contract={
                            "allOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "summary": {"type": "string"},
                                    },
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "risk": {"type": "string"},
                                    },
                                },
                            ]
                        },
                    ),
                    _step(
                        ref="step_b",
                        name="Summarize",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_bindings={
                            "question": "{{ step_1.output.structured.risk }}"
                        },
                    ),
                ]
            )
        )
        assert result.valid


class TestProductionParityValidation:
    def test_runtime_reserved_form_field_name_is_allowed(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Form flow",
            steps=[_step()],
            form_fields=[
                FormFieldSpec(
                    name="föregående_steg",
                    type="text",
                    label="Föregående steg",
                )
            ],
        )
        result = validate_spec(spec)
        assert result.valid

    def test_multiselect_requires_options(self) -> None:
        spec = FlowDraftSpecCore.model_validate(
            {
                "flow_name": "Form flow",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Extract",
                        "assistant_spec": {"instructions": "Extract."},
                        "input_source": "flow_input",
                    }
                ],
                "form_fields": [
                    {
                        "name": "Kategorier",
                        "type": "multiselect",
                        "label": "Kategorier",
                    }
                ],
            }
        )
        result = validate_spec(spec)
        assert not result.valid
        assert any("multiselect" in e.message.lower() for e in result.errors)

    def test_step_name_form_field_collision_maps_to_authored_step_ref(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Form flow",
            steps=[
                _step(
                    ref="extract_case",
                    name="CaseId",
                )
            ],
            form_fields=[
                FormFieldSpec(
                    name="caseid",
                    type="text",
                    label="Case ID",
                )
            ],
        )

        result = validate_spec(spec)

        assert any(
            error.code == "variable_alias_collision"
            and error.step_ref == "extract_case"
            and "conflicts with form field name" in error.message
            for error in result.errors
        )

    def test_runtime_input_question_must_reference_step_input(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Upload",
                        input_bindings={"question": "Sammanfatta filen"},
                        input_config={"runtime_input": {"enabled": True}},
                    )
                ]
            )
        )
        assert not result.valid
        assert any("step_input" in e.message for e in result.errors)

    def test_runtime_input_literal_substring_does_not_count_as_consumed(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Upload",
                        input_bindings={"question": "Literal step_input.text marker"},
                        input_config={"runtime_input": {"enabled": True}},
                    )
                ]
            )
        )

        assert not result.valid
        assert any(
            e.code == "flow_step_invalid" and "step_input" in e.message
            for e in result.errors
        )

    def test_template_fill_rejects_output_contract(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Fyll DOCX",
                        output_mode=OutputMode.TEMPLATE_FILL,
                        output_type=OutputType.DOCX,
                        output_contract={
                            "type": "object",
                            "properties": {"title": {"type": "string"}},
                        },
                        output_config={
                            "bindings": {"TITLE": "{{ step_1.output.text }}"}
                        },
                    )
                ]
            )
        )
        assert not result.valid
        assert any("output_contract" in e.message for e in result.errors)

    def test_citation_mode_rejected_on_transcribe_only_audio_step(self) -> None:
        # Transcribe-only audio steps are not LLM-backed text steps, so the
        # citation sidecar cannot attach. The parity layer previously
        # swallowed this exact message as a "false negative" caused by a
        # str(enum) bug in the legacy capability caller. With the FCM-backed
        # caller, the rejection is genuine — the parity filter is gone and
        # the error must surface to builder users.
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transkribera",
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                        output_config={"citation_mode": "inline_inref_sidecar"},
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(
            e.code == "flow_step_invalid"
            and "citation_mode 'inline_inref_sidecar'" in e.message
            and "LLM-backed text step" in e.message
            for e in result.errors
        )


class TestContractInstructionLint:
    def test_warns_when_output_contract_fields_missing_from_instructions(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Extract JSON",
                        instructions="Return JSON.",
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {
                                "sammanfattning": {"type": "string"},
                                "risk": {"type": "string"},
                            },
                        },
                    )
                ]
            )
        )
        assert result.valid
        assert any(w.code == "contract_instruction_mismatch" for w in result.warnings)

    def test_json_incompatible_with_all_previous_steps(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_b",
                        name="JSON",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                        input_type=InputType.JSON,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "json_all_previous_incompatible" for e in result.errors)


class TestContractDiagnostics:
    def test_invalid_input_contract_schema_maps_once_to_authored_step(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Read input",
                        input_contract={"type": "not-a-json-schema-type"},
                    )
                ]
            )
        )

        assert not result.valid
        _assert_single_error(
            result, code="invalid_input_contract_schema", step_ref="step_a"
        )

    def test_invalid_output_contract_schema_maps_once_to_authored_step(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Return output",
                        output_type=OutputType.JSON,
                        output_contract={"type": "not-a-json-schema-type"},
                    )
                ]
            )
        )

        assert not result.valid
        _assert_single_error(
            result, code="invalid_output_contract_schema", step_ref="step_a"
        )

    def test_invalid_output_contract_schema_gates_content_checks(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Create PDF",
                        output_type=OutputType.PDF,
                        output_contract={"type": "not-a-json-schema-type"},
                    )
                ]
            )
        )

        assert not result.valid
        _assert_single_error(
            result, code="invalid_output_contract_schema", step_ref="step_a"
        )
        assert not _errors_with_code(result, "output_contract_type_mismatch")

    def test_document_input_contract_maps_once_to_authored_step(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Read document",
                        input_type=InputType.DOCUMENT,
                        input_contract={"type": "object", "properties": {}},
                    )
                ]
            )
        )

        assert not result.valid
        _assert_single_error(
            result, code="input_contract_type_mismatch", step_ref="step_a"
        )

    def test_text_output_contract_maps_once_to_authored_step(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Return text",
                        output_type=OutputType.TEXT,
                        output_contract={"type": "object", "properties": {}},
                    )
                ]
            )
        )

        assert not result.valid
        _assert_single_error(
            result, code="output_contract_type_mismatch", step_ref="step_a"
        )

    def test_template_fill_output_contract_maps_once_to_authored_step(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Fill template",
                        output_mode=OutputMode.TEMPLATE_FILL,
                        output_type=OutputType.DOCX,
                        output_contract={"type": "object", "properties": {}},
                    )
                ]
            )
        )

        assert not result.valid
        _assert_single_error(
            result,
            code="output_contract_template_fill_incompatible",
            step_ref="step_a",
        )


# ---------------------------------------------------------------------------
# Type compatibility
# ---------------------------------------------------------------------------


class TestTypeCompatibility:
    def test_text_to_text_compatible(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="A", output_type=OutputType.TEXT),
                    _step(
                        ref="step_b",
                        name="B",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                    ),
                ]
            )
        )
        assert result.valid

    def test_text_to_json_compatible(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="A", output_type=OutputType.TEXT),
                    _step(
                        ref="step_b",
                        name="B",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                    ),
                ]
            )
        )
        assert result.valid

    def test_json_to_text_compatible(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="A", output_type=OutputType.JSON),
                    _step(
                        ref="step_b",
                        name="B",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                    ),
                ]
            )
        )
        assert result.valid

    def test_pdf_to_audio_incompatible(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="A", output_type=OutputType.PDF),
                    _step(
                        ref="step_b",
                        name="B",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.AUDIO,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "incompatible_type_chain" for e in result.errors)
        _assert_single_error(result, code="incompatible_type_chain", step_ref="step_b")

    def test_docx_to_json_incompatible(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="A", output_type=OutputType.DOCX),
                    _step(
                        ref="step_b",
                        name="B",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "incompatible_type_chain" for e in result.errors)
        _assert_single_error(result, code="incompatible_type_chain", step_ref="step_b")

    def test_multiple_incompatible_pairs_are_reported_per_pair(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="A", output_type=OutputType.DOCX),
                    _step(
                        ref="step_b",
                        name="B",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.DOCX,
                    ),
                    _step(
                        ref="step_c",
                        name="C",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                    ),
                ]
            )
        )

        errors = _errors_with_code(result, "incompatible_type_chain")
        assert [error.step_ref for error in errors] == ["step_b", "step_c"]

    def test_any_input_accepts_anything(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="A", output_type=OutputType.JSON),
                    _step(
                        ref="step_b",
                        name="B",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.ANY,
                    ),
                ]
            )
        )
        assert result.valid


# ---------------------------------------------------------------------------
# Transcribe-only constraints
# ---------------------------------------------------------------------------


class TestTranscribeOnly:
    def test_transcribe_only_requires_audio(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        input_type=InputType.TEXT,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "transcribe_only_violation" for e in result.errors)
        _assert_single_error(
            result, code="transcribe_only_violation", step_ref="step_a"
        )

    def test_transcribe_only_requires_text_output(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.JSON,
                    ),
                ]
            )
        )
        assert not result.valid
        _assert_single_error(
            result, code="transcribe_only_violation", step_ref="step_a"
        )

    def test_valid_transcribe_only(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                ]
            )
        )
        assert result.valid

    def test_audio_transcription_publish_config_errors_stay_suppressed(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.PASS_THROUGH,
                        output_type=OutputType.TEXT,
                    ),
                ]
            )
        )

        assert result.valid


# ---------------------------------------------------------------------------
# Template fill constraints
# ---------------------------------------------------------------------------


class TestTemplateFill:
    def test_template_fill_requires_docx(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        output_mode=OutputMode.TEMPLATE_FILL,
                        output_type=OutputType.TEXT,
                    ),
                ]
            )
        )
        assert not result.valid
        assert any(e.code == "template_fill_requires_docx" for e in result.errors)
        _assert_single_error(
            result, code="template_fill_requires_docx", step_ref="step_a"
        )

    def test_template_fill_with_docx_valid(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        output_mode=OutputMode.TEMPLATE_FILL,
                        output_type=OutputType.DOCX,
                    ),
                ]
            )
        )
        assert result.valid


# ---------------------------------------------------------------------------
# Model / KB reference validation
# ---------------------------------------------------------------------------


class TestReferenceValidation:
    def test_unknown_model_ref_rejected(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        instructions="Test",
                    ),
                ]
            ),
            available_model_refs={"gpt-4", "claude-3"},
        )
        # step has no model_ref (None) so should pass
        assert result.valid

    def test_unknown_model_ref_error(self) -> None:
        steps = [
            StepSpec(
                plan_step_ref="step_a",
                name="Test",
                assistant_spec=AssistantSpec(
                    instructions="Test",
                    model_ref="nonexistent-model",
                ),
                input_source=InputSource.FLOW_INPUT,
            ),
        ]
        result = validate_spec(
            _spec(steps),
            available_model_refs={"gpt-4", "claude-3"},
        )
        assert not result.valid
        assert any(e.code == "unknown_model_ref" for e in result.errors)

    def test_valid_model_ref_passes(self) -> None:
        steps = [
            StepSpec(
                plan_step_ref="step_a",
                name="Test",
                assistant_spec=AssistantSpec(
                    instructions="Test",
                    model_ref="gpt-4",
                ),
                input_source=InputSource.FLOW_INPUT,
            ),
        ]
        result = validate_spec(
            _spec(steps),
            available_model_refs={"gpt-4", "claude-3"},
        )
        assert result.valid

    def test_unknown_kb_ref_rejected(self) -> None:
        steps = [
            StepSpec(
                plan_step_ref="step_a",
                name="Test",
                assistant_spec=AssistantSpec(
                    instructions="Test",
                    knowledge_refs=["nonexistent_kb"],
                ),
                input_source=InputSource.FLOW_INPUT,
            ),
        ]
        result = validate_spec(
            _spec(steps),
            available_kb_refs={"kb_policy"},
        )
        assert not result.valid
        assert any(e.code == "unknown_kb_ref" for e in result.errors)

    def test_no_ref_validation_when_none(self) -> None:
        """When available refs are None, skip ref validation."""
        steps = [
            StepSpec(
                plan_step_ref="step_a",
                name="Test",
                assistant_spec=AssistantSpec(
                    instructions="Test",
                    model_ref="anything",
                    knowledge_refs=["anything"],
                ),
                input_source=InputSource.FLOW_INPUT,
            ),
        ]
        result = validate_spec(
            _spec(steps),
            available_model_refs=None,
            available_kb_refs=None,
        )
        assert result.valid


# ---------------------------------------------------------------------------
# Quality lint
# ---------------------------------------------------------------------------


class TestQualityLint:
    def test_all_previous_steps_overuse_warned(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_b",
                        name="Second",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                    ),
                    _step(
                        ref="step_c",
                        name="Third",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                    ),
                ]
            )
        )
        assert result.valid
        assert any(w.code == "all_previous_overuse" for w in result.warnings)

    def test_single_all_previous_no_warning(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_b",
                        name="Second",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                    ),
                ]
            )
        )
        assert result.valid
        assert not any(w.code == "all_previous_overuse" for w in result.warnings)

    def test_vague_step_name_warned(self) -> None:
        result = validate_spec(_spec([_step(name="Steg")]))
        assert result.valid
        assert any(w.code == "vague_step_name" for w in result.warnings)

    def test_short_step_name_warned(self) -> None:
        result = validate_spec(_spec([_step(name="AB")]))
        assert result.valid
        assert any(w.code == "vague_step_name" for w in result.warnings)

    def test_descriptive_step_name_no_warning(self) -> None:
        result = validate_spec(_spec([_step(name="Extrahera fakta")]))
        assert result.valid
        assert not any(w.code == "vague_step_name" for w in result.warnings)

    def test_multi_goal_prompt_warned(self) -> None:
        long_instructions = (
            "Extrahera alla viktiga fakta och sedan bedöm konsekvenserna "
            + ("x " * 150)
        )
        result = validate_spec(_spec([_step(instructions=long_instructions)]))
        assert result.valid
        assert any(w.code == "multi_goal_prompt" for w in result.warnings)

    def test_short_multi_goal_no_warning(self) -> None:
        """Short prompts with 'och sedan' are fine — it's the combo with length."""
        result = validate_spec(
            _spec([_step(instructions="Extrahera data och sedan summera")])
        )
        assert result.valid
        assert not any(w.code == "multi_goal_prompt" for w in result.warnings)

    def test_section_writer_table_format_no_multi_goal_warning(self) -> None:
        instructions = (
            "Skriv avsnittet Resursåtgång i form av tidsuppskattning och "
            "personella resurser. Inled med en kort sammanfattning och skapa "
            "därefter en tabell med kolumnerna Roll/kompetens, Ansvar/aktivitet, "
            "Intern/extern resurs, Uppskattad tidsåtgång, Timkostnad, Beräknad "
            "kostnad och Kommentar. Använd roller som nämns i dokumentet. Om "
            "roller inte nämns men tydligt kan härledas, markera dem som "
            "'Bedömd roll utifrån underlaget'. Om timmar eller kostnader saknas, "
            "skriv [Behöver kompletteras: tidsuppskattning] respektive "
            "[Behöver kompletteras: kostnadsuppgift]."
        )
        result = validate_spec(
            _spec([_step(name="Skriv Resursåtgång", instructions=instructions)])
        )
        assert result.valid
        assert not any(w.code == "multi_goal_prompt" for w in result.warnings)

    def test_report_assembler_quality_check_no_multi_goal_warning(self) -> None:
        instructions = (
            "Granska samtliga skrivna avsnitt som en helhet och säkerställ att "
            "problem/nuläge leder vidare till lösningsförslag/nyläge, att "
            "resursåtgång, tidplan, kostnader, nyttor, finansiering, ansvar "
            "för nyttorealisering, förändringskomplexitet och plan för "
            "nyttorealisering hänger ihop logiskt, att inga fakta har lagts "
            "till utan stöd i underlaget och att alla saknade uppgifter är "
            "tydligt markerade. Sammanställ därefter ett sammanhållet "
            "beslutsunderlag med de rubriker som användaren efterfrågat, redo "
            "för generering som Word-dokument."
        )
        result = validate_spec(
            _spec(
                [
                    _step(
                        name="Kvalitetsgranska och sammanställ beslutsunderlaget",
                        instructions=instructions,
                    )
                ]
            )
        )
        assert result.valid
        assert not any(w.code == "multi_goal_prompt" for w in result.warnings)

    def test_real_multi_goal_prompt_still_warns_with_report_words(self) -> None:
        instructions = (
            "Skriv en rapport med bakgrund, risker och rekommendationer och sedan "
            "extrahera alla datum, kostnader, ansvariga och avvikande villkor till "
            "separata strukturerade fält och därefter kontrollera varje källa mot "
            "en extern policy innan sluttexten skrivs. Beskriv också hur varje "
            "fält ska användas i nästa steg och skapa en separat lista över "
            "saknade uppgifter som användaren ska komplettera."
        )

        result = validate_spec(
            _spec([_step(name="Skriv rapport", instructions=instructions)])
        )

        assert result.valid
        assert any(w.code == "multi_goal_prompt" for w in result.warnings)

    def test_single_step_flow_info(self) -> None:
        result = validate_spec(_spec([_step(name="Sammanfatta")]))
        assert result.valid
        assert any(
            w.code == "single_step_flow" and w.severity == LintSeverity.INFO
            for w in result.warnings
        )

    def test_multi_step_no_single_step_warning(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(ref="step_a", name="First"),
                    _step(
                        ref="step_b",
                        name="Second",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ]
            )
        )
        assert result.valid
        assert not any(w.code == "single_step_flow" for w in result.warnings)

    def test_lint_only_runs_on_valid_spec(self) -> None:
        """Lint should NOT run if hard validation fails."""
        result = validate_spec(_spec([]))  # Empty = hard fail
        assert not result.valid
        assert result.warnings == []  # No lint ran

    def test_source_material_boundary_missing_underlag_warned(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transkribera ljud",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Strukturera transkription",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {"transcription_text": {"type": "string"}},
                        },
                    ),
                    _step(
                        ref="step_c",
                        name="Identifiera mötesmetadata",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {"meeting_title": {"type": "string"}},
                        },
                    ),
                    _step(
                        ref="step_d",
                        name="Skapa mötesprotokoll",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {"protocol_sections": {"type": "string"}},
                        },
                    ),
                    _step(
                        ref="step_e",
                        name="Förbered DOCX-innehåll",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                        input_type=InputType.TEXT,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_f",
                        name="Skapa DOCX",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.DOCX,
                    ),
                ]
            )
        )

        assert result.valid
        assert any(
            warning.code == "source_material_boundary_missing_underlag"
            and warning.step_ref == "step_c"
            for warning in result.warnings
        )
        assert any(
            warning.code == "source_material_boundary_missing_underlag"
            and warning.step_ref == "step_d"
            for warning in result.warnings
        )

    def test_source_material_boundary_missing_underlag_warned_for_text_report(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transcribe source",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Extract decisions",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.JSON,
                    ),
                    _step(
                        ref="step_c",
                        name="Extract actions",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.JSON,
                    ),
                    _step(
                        ref="step_d",
                        name="Write final report",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.TEXT,
                    ),
                ]
            )
        )

        assert result.valid
        assert any(
            warning.code == "source_material_boundary_missing_underlag"
            and warning.step_ref == "step_c"
            for warning in result.warnings
        )
        assert any(
            warning.code == "source_material_boundary_missing_underlag"
            and warning.step_ref == "step_d"
            for warning in result.warnings
        )

    def test_source_material_boundary_text_report_complete_underlag_does_not_warn(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transcribe source",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Extract decisions",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.JSON,
                    ),
                    _step(
                        ref="step_c",
                        name="Write final report",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.TEXT,
                        input_bindings={
                            "question": (
                                "{{ step_b.output.structured }}\n\n"
                                "Source material: {{ step_a.output.text }}"
                            )
                        },
                    ),
                ]
            )
        )

        assert result.valid
        assert not any(
            warning.code == "source_material_boundary_missing_underlag"
            for warning in result.warnings
        )

    def test_source_material_boundary_does_not_warn_for_text_chain_without_json(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Read source",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.TEXT,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Draft response",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_c",
                        name="Finalize response",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.TEXT,
                    ),
                ]
            )
        )

        assert result.valid
        assert not any(
            warning.code == "source_material_boundary_missing_underlag"
            for warning in result.warnings
        )

    def test_source_material_boundary_does_not_warn_for_pure_json_chain(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transcribe source",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Extract facts",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.JSON,
                    ),
                    _step(
                        ref="step_c",
                        name="Extract decisions",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.JSON,
                    ),
                ]
            )
        )

        assert result.valid
        assert not any(
            warning.code == "source_material_boundary_missing_underlag"
            for warning in result.warnings
        )

    def test_source_material_boundary_allows_structured_subfield_underlag(self) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transkribera ljud",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                    ),
                    _step(
                        ref="step_b",
                        name="Extrahera IBIC",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.TEXT,
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {
                                "brukare": {
                                    "type": "object",
                                    "properties": {
                                        "kan_uttrycka_behov_sjalv": {"type": "string"}
                                    },
                                }
                            },
                        },
                    ),
                    _step(
                        ref="step_c",
                        name="Skapa DOCX",
                        input_source=InputSource.PREVIOUS_STEP,
                        input_type=InputType.JSON,
                        output_type=OutputType.DOCX,
                        input_bindings={
                            "question": (
                                "Behov: "
                                "{{ step_b.output.structured.brukare.kan_uttrycka_behov_sjalv }}"
                            )
                        },
                    ),
                ]
            )
        )

        assert result.valid
        assert not any(
            warning.code == "source_material_boundary_missing_underlag"
            for warning in result.warnings
        )

    def test_runtime_input_without_binding_does_not_warn_for_transcribe_only_step(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Transkribera ljud",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_mode=OutputMode.TRANSCRIBE_ONLY,
                        output_type=OutputType.TEXT,
                        input_config={
                            "runtime_input": {"enabled": True, "input_format": "audio"}
                        },
                    ),
                    _step(
                        ref="step_b",
                        name="Sammanfatta",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ]
            )
        )
        assert result.valid
        assert not any(
            w.code == "runtime_input_without_binding" for w in result.warnings
        )

    def test_runtime_input_without_binding_does_not_warn_for_document_flow_input_step(
        self,
    ) -> None:
        result = validate_spec(
            _spec(
                [
                    _step(
                        ref="step_a",
                        name="Analysera dokument",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.DOCUMENT,
                        output_type=OutputType.TEXT,
                        input_config={
                            "runtime_input": {
                                "enabled": True,
                                "input_format": "document",
                            }
                        },
                    ),
                ]
            )
        )
        assert result.valid
        assert not any(
            w.code == "runtime_input_without_binding" for w in result.warnings
        )
