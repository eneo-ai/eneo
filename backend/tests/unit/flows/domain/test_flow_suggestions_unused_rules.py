"""The suggestions about data nobody reads: contract fields, whole results,
form fields, and steps that only pass a result on."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    SuggestionFlow,
    SuggestionStep,
    analyze_flow,
)

_IDS = [UUID(int=index) for index in range(1, 40)]
_CONTRACT = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"],
}


def _step(order: int, **columns: Any) -> SuggestionStep:
    values: dict[str, Any] = {
        "id": _IDS[order],
        "step_order": order,
        "user_description": f"Steg {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "text",
        "input_bindings": None,
        "input_config": None,
        "output_mode": "pass_through",
        "output_type": "text",
        "output_contract": None,
        "output_config": None,
        "prompt_text": "Gör så här.",
        "assistant_id": UUID(int=100 + order),
    }
    return SuggestionStep(**{**values, **columns})


def _of(
    code: FlowSuggestionCode,
    steps: list[SuggestionStep],
    metadata: Mapping[str, object] | None = None,
) -> list[FlowSuggestion]:
    return [
        suggestion
        for suggestion in analyze_flow(
            SuggestionFlow(steps=steps, metadata_json=metadata)
        )
        if suggestion.code is code
    ]


# --------------------------------------------------------------------------- #
# unread_contract_fields
# --------------------------------------------------------------------------- #

_FIELDS = FlowSuggestionCode.UNREAD_CONTRACT_FIELDS


def _producer(**columns: Any) -> SuggestionStep:
    return _step(1, output_type="json", output_contract=_CONTRACT, **columns)


def _title_reader(order: int = 2, **columns: Any) -> SuggestionStep:
    return _step(
        order,
        input_source="flow_input",
        input_bindings={"question": "{{ step_1.output.structured.title }}"},
        **columns,
    )


def test_a_contract_field_no_later_step_reads_is_patched_away() -> None:
    (suggestion,) = _of(_FIELDS, [_producer(), _title_reader()])

    assert suggestion.steps == (_IDS[1],)
    assert suggestion.impact.level == "medium"
    assert suggestion.params == {"fields": ["body"], "read_fields": ["title"]}
    assert suggestion.fix.kind == "patch"
    assert suggestion.fix.patch == {
        "definition": {},
        "step_edits": [
            {
                "step_id": str(_IDS[1]),
                "changes": {
                    "output_contract": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    }
                },
            }
        ],
    }


def test_a_field_read_in_a_template_fill_binding_counts_as_read() -> None:
    template_fill = _step(
        3,
        input_source="flow_input",
        output_mode="template_fill",
        output_type="docx",
        output_config={"bindings": {"brodtext": "{{ step_1.output.structured.body }}"}},
    )

    assert _of(_FIELDS, [_producer(), _title_reader(), template_fill]) == []


def test_no_contract_suggestion_while_a_later_step_reads_the_whole_result() -> None:
    whole_text = _step(3, input_source="flow_input", prompt_text="{{ step_1 }}")
    whole_value = _step(
        3,
        input_source="flow_input",
        input_bindings={
            "source_refs": [{"step_ref": "step_1", "output": "structured"}]
        },
    )

    assert _of(_FIELDS, [_producer(), _title_reader(), whole_text]) == []
    assert _of(_FIELDS, [_producer(), _title_reader(), whole_value]) == []


def test_the_last_step_a_reviewed_step_and_an_unread_step_are_excluded() -> None:
    assert _of(_FIELDS, [_producer()]) == []
    assert _of(_FIELDS, [_producer(has_review_policy=True), _title_reader()]) == []
    # Nobody reads it at all: that is unread_result.
    assert _of(_FIELDS, [_producer(), _step(2, input_source="flow_input")]) == []


def test_the_contract_fingerprint_follows_the_unread_fields() -> None:
    (before,) = _of(_FIELDS, [_producer(), _title_reader()])
    (reworded,) = _of(
        _FIELDS, [_producer(prompt_text="Ny text."), _title_reader(prompt_text="Ny.")]
    )
    body_reader = _step(
        2,
        input_source="flow_input",
        input_bindings={"question": "{{ step_1.output.structured.body }}"},
    )
    (other,) = _of(_FIELDS, [_producer(), body_reader])

    assert reworded.fingerprint == before.fingerprint
    assert other.fingerprint != before.fingerprint


# --------------------------------------------------------------------------- #
# unread_result
# --------------------------------------------------------------------------- #

_UNREAD = FlowSuggestionCode.UNREAD_RESULT


def test_a_result_no_later_step_reads_is_advice_with_a_remove_patch() -> None:
    (suggestion,) = _of(
        _UNREAD, [_step(1), _step(2, input_source="flow_input"), _step(3)]
    )

    assert suggestion.steps == (_IDS[1],)
    assert suggestion.impact.level == "medium"
    assert suggestion.fix.kind == "advice"
    assert suggestion.fix.patch is None
    assert suggestion.params["remove_patch"] == {
        "definition": {},
        "step_order": [{"step_id": str(_IDS[2])}, {"step_id": str(_IDS[3])}],
    }


def test_a_read_in_any_channel_keeps_a_result() -> None:
    http_post = _step(
        2,
        input_source="flow_input",
        output_mode="http_post",
        output_config={
            "url": "https://example.org/{{ step_1.output.text }}",
            "auth": {"mode": "none"},
            "timeout_seconds": 30,
            "body": {"mode": "auto"},
            "custom_headers": [],
        },
    )

    assert _of(_UNREAD, [_step(1), http_post, _step(3)]) == []


def test_unread_result_exclusions() -> None:
    def unread(**columns: Any) -> list[FlowSuggestion]:
        return _of(_UNREAD, [_step(1, **columns), _step(2, input_source="flow_input")])

    assert unread(has_review_policy=True) == []
    assert unread(output_type="pdf") == []
    assert unread(output_mode="transcribe_only") == []
    assert unread(output_mode="speaker_mapping") == []
    assert unread(input_source="tool") == []
    # The last step's result is the flow's output.
    assert _of(_UNREAD, [_step(1)]) == []


# --------------------------------------------------------------------------- #
# relay_step
# --------------------------------------------------------------------------- #

_RELAY = FlowSuggestionCode.RELAY_STEP


def _relay(order: int = 2, **columns: Any) -> SuggestionStep:
    return _step(order, output_mode="compose_text", prompt_text=None, **columns)


def test_a_compose_text_relay_is_patched_by_reading_its_source() -> None:
    (suggestion,) = _of(
        _RELAY,
        [
            _step(1),
            _relay(),
            _step(3, prompt_text="Svara.\n{{ Steg 2.output.text }}"),
            _step(4, prompt_text="{{ step_3.output.text }}"),
        ],
    )

    assert suggestion.steps == (_IDS[2], _IDS[1])
    assert suggestion.impact.level == "low"
    assert suggestion.params["source_step_order"] == 1
    assert [reader["step_order"] for reader in suggestion.params["readers"]] == [3]
    assert suggestion.fix.kind == "patch"
    assert suggestion.fix.patch == {
        "definition": {},
        "assistants": [
            {
                "assistant_id": str(UUID(int=103)),
                "step_id": str(_IDS[3]),
                "changes": {
                    "prompt": {
                        "text": "Svara.\n{{ step_1.output.text }}",
                        "description": None,
                    }
                },
            }
        ],
        "step_order": [
            {"step_id": str(_IDS[1])},
            {"step_id": str(_IDS[3])},
            {"step_id": str(_IDS[4])},
        ],
    }


def test_a_relay_read_in_an_underlag_is_rewritten_and_renumbered() -> None:
    (suggestion,) = _of(
        _RELAY,
        [
            _step(1),
            _relay(),
            _step(3),
            _step(
                4,
                input_source="flow_input",
                input_bindings={
                    "question": "{{ step_3 }}",
                    "source_refs": [{"step_ref": "step_2", "output": "text"}],
                },
            ),
        ],
    )

    assert suggestion.fix.patch is not None
    assert suggestion.fix.patch["step_edits"] == [
        {
            "step_id": str(_IDS[4]),
            "changes": {
                "input_bindings": {
                    "question": "{{ step_2 }}",
                    "source_refs": [{"step_ref": "step_1", "output": "text"}],
                }
            },
        }
    ]


def test_a_copy_input_relay_of_a_json_step_rewrites_a_declared_path() -> None:
    source = _step(1, output_type="json", output_contract=_CONTRACT)
    copy = _step(
        2,
        input_type="json",
        output_type="json",
        output_mode="copy_input",
        prompt_text=None,
    )
    reader = _step(
        3, input_source="flow_input", prompt_text="{{ step_2.output.structured.title }}"
    )

    (suggestion,) = _of(_RELAY, [source, copy, reader])

    assert suggestion.fix.kind == "patch"
    assert suggestion.fix.patch is not None
    assert suggestion.fix.patch["assistants"][0]["changes"]["prompt"]["text"] == (
        "{{ step_1.output.structured.title }}"
    )


def test_a_relay_is_assisted_when_a_read_cannot_be_rewritten() -> None:
    source = _step(1, output_type="json", output_contract=_CONTRACT)
    copy = _step(
        2,
        input_type="json",
        output_type="json",
        output_mode="copy_input",
        prompt_text=None,
    )
    undeclared = _step(
        3, input_source="flow_input", prompt_text="{{ step_2.output.structured.other }}"
    )
    in_config = _step(
        3,
        input_source="flow_input",
        output_mode="template_fill",
        output_type="docx",
        output_config={"bindings": {"x": "{{ step_2.output.structured.title }}"}},
    )
    # The reader's previous_step would come to read step 2 of a flow where
    # the relay reads step 1 by name.
    named_source = [
        _step(1),
        _step(2, input_source="flow_input"),
        _relay(
            3, input_bindings={"question": "{{ Steg 1 }}"}, input_source="flow_input"
        ),
        _step(4),
    ]

    for steps in ([source, copy, undeclared], [source, copy, in_config], named_source):
        (suggestion,) = _of(_RELAY, steps)
        assert suggestion.fix.kind == "assisted", steps


def test_a_relay_of_the_run_input_or_with_an_override_is_assisted() -> None:
    run_input = _relay(1, input_source="flow_input")
    (of_run_input,) = _of(_RELAY, [run_input, _step(2)])
    (overridden,) = _of(
        _RELAY, [_step(1), _relay(output_classification_override=1), _step(3)]
    )

    assert of_run_input.fix.kind == "assisted"
    assert of_run_input.params["source_step_order"] is None
    assert of_run_input.steps == (_IDS[1],)
    assert overridden.fix.kind == "assisted"


def test_no_relay_for_an_unread_relay_a_review_or_more_than_one_read() -> None:
    assert _of(_RELAY, [_step(1), _relay(), _step(3, input_source="flow_input")]) == []
    assert _of(_RELAY, [_step(1), _relay(has_review_policy=True), _step(3)]) == []
    two_reads = _relay(
        3,
        input_source="flow_input",
        input_bindings={"question": "{{ step_1 }} {{ step_2 }}"},
    )
    assert _of(_RELAY, [_step(1), _step(2), two_reads, _step(4)]) == []


def test_a_relay_keeps_its_fingerprint_when_the_relay_before_it_goes() -> None:
    # Steps 2 and 3 each pass on the step before. Removing step 2 renumbers
    # step 3 and makes it pass on step 1: still the same relay.
    first, second = _of(
        _RELAY, [_step(1), _relay(2), _relay(3, id=_IDS[30]), _step(4, id=_IDS[31])]
    )
    (after,) = _of(_RELAY, [_step(1), _relay(2, id=_IDS[30]), _step(3, id=_IDS[31])])

    assert after.fingerprint == second.fingerprint
    assert after.fingerprint != first.fingerprint
    assert after.steps == (_IDS[30], _IDS[1])
    assert after.params["source_step_order"] == 1


def test_a_relay_read_another_way_is_another_relay() -> None:
    (by_input,) = _of(_RELAY, [_step(1), _relay(), _step(3)])
    (by_question,) = _of(
        _RELAY,
        [
            _step(1),
            _relay(
                input_source="flow_input",
                input_bindings={"question": "{{ step_1.output.text }}"},
            ),
            _step(3),
        ],
    )

    assert by_question.fingerprint != by_input.fingerprint


# --------------------------------------------------------------------------- #
# unused_form_field
# --------------------------------------------------------------------------- #

_FORM = FlowSuggestionCode.UNUSED_FORM_FIELD
_METADATA = {
    "wizard": {"transcription_enabled": False},
    "form_schema": {
        "fields": [
            {"name": "kommun", "type": "text", "required": True},
            {"name": "ärende", "type": "text"},
        ]
    },
}


def _question(text: str) -> SuggestionStep:
    return _step(1, input_bindings={"question": text})


def test_a_form_field_no_step_reads_is_patched_out_of_the_form() -> None:
    (suggestion,) = _of(_FORM, [_question("{{ flow_input.kommun }}")], _METADATA)

    assert suggestion.steps == ()
    assert suggestion.impact.level == "low"
    assert suggestion.params == {"field": "ärende"}
    assert suggestion.fix.patch == {
        "definition": {
            "metadata_json": {
                "wizard": {"transcription_enabled": False},
                "form_schema": {
                    "fields": [{"name": "kommun", "type": "text", "required": True}]
                },
            }
        }
    }


def test_a_bare_name_a_prompt_or_a_configuration_reads_a_form_field() -> None:
    bare = [_question("{{ kommun }} {{ ärende }}")]
    in_prompt = [
        _question("{{ kommun }}"),
        _step(2, prompt_text="{{ flow_input.ärende }}"),
    ]
    in_config = [
        _question("{{ kommun }}"),
        _step(
            2,
            output_mode="template_fill",
            output_type="docx",
            output_config={"bindings": {"x": "{{ flow_input.ärende }}"}},
        ),
    ]

    for steps in (bare, in_prompt, in_config):
        assert _of(_FORM, steps, _METADATA) == [], steps


def test_no_form_suggestion_while_a_step_takes_the_whole_run_input() -> None:
    assert _of(_FORM, [_step(1)], _METADATA) == []
    assert _of(_FORM, [_question("{{ flow_input }}")], _METADATA) == []


def test_the_form_fingerprint_is_the_field() -> None:
    (before,) = _of(_FORM, [_question("{{ kommun }}")], _METADATA)
    (renamed,) = _of(
        _FORM,
        [
            _step(
                1, user_description="Läs", input_bindings={"question": "{{ kommun }} x"}
            )
        ],
        _METADATA,
    )

    assert renamed.fingerprint == before.fingerprint
