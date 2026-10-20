"""The flow definition: step union, structural validation, stable step ids."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.definition import (
    ComposeStep,
    DocumentStep,
    FlowDefinition,
    FlowDefinitionError,
    FormField,
    LlmStep,
    ReviewStep,
    TranscribeStep,
    assign_step_ids,
    definition_summary,
    review_target_key,
    validate_definition,
)


def _text_field(key: str = "topic", **extra) -> FormField:
    return FormField(key=key, label=key.title(), type="text", **extra)


def _llm(key: str, **extra) -> LlmStep:
    # A fixed input keeps helper steps valid in first position too.
    extra.setdefault("input", "fixed input")
    extra.setdefault("prompt", "Do it")
    return LlmStep(key=key, name=key.title(), **extra)


def _errors(definition: FlowDefinition) -> list[str]:
    with pytest.raises(FlowDefinitionError) as exc:
        validate_definition(definition)
    return exc.value.errors


# --- Discriminated union ---


def test_kind_selects_the_step_model():
    definition = FlowDefinition.model_validate(
        {
            "steps": [
                {"key": "draft", "name": "Draft", "kind": "llm", "prompt": "p"},
                {"key": "wrap", "name": "Wrap", "kind": "compose", "template": "x"},
                {"key": "check", "name": "Check", "kind": "review"},
            ]
        }
    )
    assert [type(step) for step in definition.steps] == [
        LlmStep,
        ComposeStep,
        ReviewStep,
    ]
    assert definition.steps[0].input == "{{previous}}"
    assert definition.steps[2].mode == "edit"


def test_unknown_kind_and_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        FlowDefinition.model_validate(
            {"steps": [{"key": "a", "name": "A", "kind": "magic"}]}
        )
    with pytest.raises(ValidationError):
        FlowDefinition.model_validate(
            {
                "steps": [
                    {
                        "key": "a",
                        "name": "A",
                        "kind": "compose",
                        "template": "t",
                        "extra": 1,
                    }
                ]
            }
        )


def test_json_output_schema_round_trips_through_alias():
    step = LlmStep.model_validate(
        {
            "key": "k",
            "name": "K",
            "prompt": "p",
            "output": {"type": "json", "schema": {"type": "object"}},
        }
    )
    assert step.output.schema_ == {"type": "object"}
    dumped = FlowDefinition(steps=[step]).model_dump(mode="json", by_alias=True)
    assert dumped["steps"][0]["output"]["schema"] == {"type": "object"}
    assert FlowDefinition.model_validate(dumped).steps[0].output.schema_ == {
        "type": "object"
    }


def test_keys_must_be_short_lowercase_identifiers():
    with pytest.raises(ValidationError):
        _llm("Not Valid")
    with pytest.raises(ValidationError):
        _text_field("1starts_with_digit")


# --- validate_definition rules ---


def test_valid_definition_passes():
    definition = FlowDefinition(
        form_fields=[_text_field(), FormField(key="doc", label="Doc", type="file")],
        steps=[
            _llm("draft", input="{{form.topic}}", files_from=["doc"]),
            ReviewStep(key="check", name="Check", of="draft"),
            ComposeStep(
                key="wrap", name="Wrap", template="{{steps.draft}} {{previous}}"
            ),
        ],
    )
    validate_definition(definition)


def test_select_field_needs_options():
    errors = _errors(
        FlowDefinition(
            form_fields=[FormField(key="mode", label="Mode", type="select")],
            steps=[_llm("a")],
        )
    )
    assert errors == ["select field 'mode' needs options"]


def test_empty_flow_and_duplicate_keys():
    assert _errors(FlowDefinition()) == ["a flow needs at least one step"]
    errors = _errors(FlowDefinition(steps=[_llm("a"), _llm("a")]))
    assert "step key 'a' is used more than once" in errors


def test_references_must_name_form_fields_or_earlier_steps():
    errors = _errors(
        FlowDefinition(
            form_fields=[_text_field()],
            steps=[
                _llm("first", input="{{form.missing}} {{steps.second}} {{previous}}"),
                _llm("second", input="{{form.topic}}"),
            ],
        )
    )
    assert errors == [
        "step 'first' input: {{form.missing}} names no form field",
        "step 'first' input: {{steps.second}} must name an earlier step",
        "step 'first' input: {{previous}} has no previous step",
    ]


def test_json_path_only_reads_json_steps():
    errors = _errors(
        FlowDefinition(
            steps=[
                _llm("text_step"),
                ComposeStep(
                    key="wrap", name="Wrap", template="{{steps.text_step.json.title}}"
                ),
            ]
        )
    )
    assert errors == [
        "step 'wrap' template: {{steps.text_step.json.title}} reads JSON from a "
        "step that produces text"
    ]
    validate_definition(
        FlowDefinition(
            steps=[
                _llm("js", output={"type": "json", "schema": {"type": "object"}}),
                ComposeStep(
                    key="wrap", name="Wrap", template="{{steps.js.json.title}}"
                ),
            ]
        )
    )


def test_malformed_reference_is_reported_with_its_location():
    errors = _errors(FlowDefinition(steps=[_llm("a", prompt="{{steps}}")]))
    assert errors[0].startswith("step 'a' prompt: Unknown reference '{{steps}}'")


def test_files_from_must_name_file_fields():
    errors = _errors(
        FlowDefinition(
            form_fields=[_text_field()],
            steps=[_llm("a", files_from=["topic", "nothing"])],
        )
    )
    assert errors == [
        "step 'a' files_from 'topic' is not a file field",
        "step 'a' files_from names no form field 'nothing'",
    ]


def test_document_step_needs_template_xor_content():
    neither = DocumentStep(key="d", name="D")
    both = DocumentStep(key="d", name="D", template_file_id=uuid4(), content="x")
    values_without_template = DocumentStep(
        key="d", name="D", content="x", values={"a": "b"}
    )
    for step in (neither, both):
        assert "step 'd' needs exactly one of template_file_id or content" in _errors(
            FlowDefinition(steps=[step])
        )
    assert _errors(FlowDefinition(steps=[values_without_template])) == [
        "step 'd' values only apply with a template file"
    ]


def test_review_step_rules():
    assert "step 'r' cannot be the first step" in _errors(
        FlowDefinition(steps=[ReviewStep(key="r", name="R")])
    )
    assert "step 'r' reviews 'later', which is not earlier" in _errors(
        FlowDefinition(steps=[_llm("a"), ReviewStep(key="r", name="R", of="later")])
    )
    assert "step 'r2' cannot review another review step" in _errors(
        FlowDefinition(
            steps=[
                _llm("a"),
                ReviewStep(key="r1", name="R1"),
                ReviewStep(key="r2", name="R2"),
            ]
        )
    )


def test_transcribe_step_rules():
    errors = _errors(
        FlowDefinition(
            form_fields=[
                _text_field("notes"),
                FormField(key="audio", label="A", type="audio"),
            ],
            steps=[
                TranscribeStep(key="t1", name="T", source="notes"),
                TranscribeStep(key="t2", name="T", source="nope"),
                TranscribeStep(
                    key="t3",
                    name="T",
                    source="audio",
                    speaker_mapping={"participants_field": "audio"},
                ),
            ],
        )
    )
    assert errors == [
        "step 't1' source 'notes' is not a file field",
        "step 't2' source names no form field 'nope'",
        "step 't3' speaker_mapping.participants_field must be a text field",
    ]


# --- assign_step_ids / review_target_key / summary ---


def test_assign_step_ids_keeps_ids_by_key_and_replaces_unknown_ones():
    previous = assign_step_ids(FlowDefinition(steps=[_llm("a"), _llm("b")]))
    a_id = previous.steps[0].id
    foreign = uuid4()
    updated = assign_step_ids(
        FlowDefinition(
            steps=[
                _llm("b"),
                _llm("a"),
                LlmStep(key="c", name="C", prompt="p", id=foreign),
            ]
        ),
        previous,
    )
    by_key = {step.key: step.id for step in updated.steps}
    assert by_key["a"] == a_id
    assert by_key["b"] == previous.steps[1].id
    assert by_key["c"] is not None and by_key["c"] != foreign


def test_review_target_key_defaults_to_previous_step():
    definition = FlowDefinition(
        steps=[
            _llm("a"),
            _llm("b"),
            ReviewStep(key="r", name="R"),
            ReviewStep(key="r2", name="R2", of="a"),
        ]
    )
    assert review_target_key(definition, definition.steps[2]) == "b"
    assert review_target_key(definition, definition.steps[3]) == "a"
    lonely = ReviewStep(key="r", name="R")
    assert review_target_key(FlowDefinition(steps=[lonely]), lonely) is None


def test_definition_summary_lists_steps_in_order():
    definition = FlowDefinition(
        steps=[_llm("a"), ComposeStep(key="b", name="B", template="t")]
    )
    assert (
        definition_summary(definition) == "1. [llm] A (key: a)\n2. [compose] B (key: b)"
    )
