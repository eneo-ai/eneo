from __future__ import annotations

from uuid import UUID

import pytest

from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_output_schema_evidence import (
    EXAMPLE_OUTPUT_MAX_DEPTH,
    EXAMPLE_OUTPUT_MAX_FIELDS,
    EXAMPLE_OUTPUT_MAX_JSON_BYTES,
    OUTPUT_SCHEMA_MAX_JSON_BYTES,
    AIBuilderAttachmentOutputSchemaCandidate,
    ExampleOutputJsonSource,
    OutputSchemaLimitExceeded,
    build_attachment_schema_candidate,
    build_output_schema_evidence,
    parse_output_schema_candidate,
    resolve_attachment_output_schema,
    resolve_example_output_schema_inference,
)


def _candidate(
    field: str,
    file_number: int,
) -> AIBuilderAttachmentOutputSchemaCandidate:
    return build_attachment_schema_candidate(
        {"type": "object", "properties": {field: {"type": "string"}}},
        source_file_ids=(UUID(int=file_number),),
    )


def _selection_conversation(
    candidates: tuple[AIBuilderAttachmentOutputSchemaCandidate, ...],
    *,
    selected_values: list[str],
    tool_name: str = "ask_structured_question",
    options: list[dict[str, object]] | None = None,
) -> list[ConversationMessage]:
    return [
        ConversationMessage(
            role="assistant",
            content="Choose a schema.",
            tool_calls=[
                {
                    "id": "call-schema",
                    "name": tool_name,
                    "arguments": {
                        "question_id": "output_schema_conflict",
                        "question": "Which schema?",
                        "options": options
                        if options is not None
                        else [
                            {
                                "id": candidate.fingerprint,
                                "label": f"Schema {index}",
                                "value": candidate.fingerprint,
                            }
                            for index, candidate in enumerate(candidates, start=1)
                        ],
                        "selection_mode": "single",
                        "allow_custom": False,
                    },
                }
            ],
        ),
        ConversationMessage(
            role="tool",
            content="Question presented.",
            tool_call_id="call-schema",
        ),
        ConversationMessage(
            role="user",
            content="Use the selected schema.",
            metadata={
                "question_answer": {
                    "question_id": "output_schema_conflict",
                    "selected_values": selected_values,
                }
            },
        ),
    ]


@pytest.mark.parametrize(
    "constant",
    ["NaN", "Infinity", "-Infinity", "1e309"],
)
def test_explicit_schema_parser_rejects_non_finite_numbers(constant: str) -> None:
    assert (
        parse_output_schema_candidate(
            '{"type":"object","properties":{},"default":' + constant + "}"
        )
        is None
    )


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_output_schema_evidence_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        build_output_schema_evidence(
            json_schema={"type": "object", "default": value},
            source="freeform_text",
            confidence="high",
            evidence=("message:invalid-schema",),
        )


def test_explicit_schema_parser_preserves_canonical_size_failure() -> None:
    raw_json = (
        '{"type":"object","allOf":['
        + ",".join('{"default":1e9}' for _ in range(5_500))
        + "]}"
    )
    assert len(raw_json.encode("utf-8")) < OUTPUT_SCHEMA_MAX_JSON_BYTES

    with pytest.raises(OutputSchemaLimitExceeded) as exc_info:
        parse_output_schema_candidate(raw_json)

    assert exc_info.value.reason == "canonical_bytes"
    assert exc_info.value.actual_value is not None
    assert exc_info.value.actual_value > OUTPUT_SCHEMA_MAX_JSON_BYTES


def test_selection_requires_exact_current_candidate_set() -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)
    conversation = _selection_conversation(
        (first, second),
        selected_values=[second.fingerprint],
    )

    selected = resolve_attachment_output_schema(
        conversation=conversation,
        candidates=(first, second),
        authoritative_evidence=None,
    )
    drifted = resolve_attachment_output_schema(
        conversation=conversation,
        candidates=(first, second, _candidate("added", 3)),
        authoritative_evidence=None,
    )

    assert selected.conflict_pending is False
    assert selected.evidence is not None
    assert selected.evidence.fingerprint == second.fingerprint
    assert drifted.conflict_pending is True
    assert drifted.evidence is None


def test_selection_rejects_valid_fingerprint_plus_spoofed_extra() -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)

    resolution = resolve_attachment_output_schema(
        conversation=_selection_conversation(
            (first, second),
            selected_values=[second.fingerprint, "spoofed"],
        ),
        candidates=(first, second),
        authoritative_evidence=None,
    )

    assert resolution.conflict_pending is True
    assert resolution.evidence is None


@pytest.mark.parametrize(
    "options",
    [
        [{"id": "not-a-fingerprint", "value": "not-a-fingerprint"}],
        [{"id": "a" * 64, "value": "b" * 64}],
        [
            {"id": "a" * 64, "value": "a" * 64},
            {"id": "a" * 64, "value": "a" * 64},
        ],
        [{"id": "a" * 64, "value": "a" * 64}, {"label": "missing identity"}],
    ],
)
def test_selection_fails_closed_for_malformed_persisted_options(
    options: list[dict[str, object]],
) -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)

    resolution = resolve_attachment_output_schema(
        conversation=_selection_conversation(
            (first, second),
            selected_values=[second.fingerprint],
            options=options,
        ),
        candidates=(first, second),
        authoritative_evidence=None,
    )

    assert resolution.conflict_pending is True
    assert resolution.evidence is None


def test_selection_ignores_question_payload_on_wrong_tool() -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)

    resolution = resolve_attachment_output_schema(
        conversation=_selection_conversation(
            (first, second),
            selected_values=[second.fingerprint],
            tool_name="propose_flow",
        ),
        candidates=(first, second),
        authoritative_evidence=None,
    )

    assert resolution.conflict_pending is True


def test_example_output_inference_builds_an_open_conservative_schema() -> None:
    source = ExampleOutputJsonSource(
        file_id=UUID(int=1),
        is_json=True,
        content=(
            '{"title":"Decision","count":2,"score":1.5,"published":true,'
            '"optional":null,"empty":[],"mixed":[1,"two"],'
            '"owner":{"name":"Ada"},"items":[{"id":1},{"id":2}]}'
        ),
        content_complete=True,
    )

    resolution = resolve_example_output_schema_inference(
        sources=(source,),
        authoritative_evidence=None,
    )

    assert resolution.outcome is not None
    assert resolution.outcome.status == "inferred"
    assert resolution.outcome.reason is None
    assert resolution.evidence is not None
    assert resolution.evidence.source == "inferred_example"
    assert resolution.evidence.strength == "inferred"
    assert resolution.evidence.source_file_ids == [source.file_id]
    schema = resolution.evidence.json_schema
    assert schema == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "count": {"type": "integer"},
            "score": {"type": "number"},
            "published": {"type": "boolean"},
            "optional": {},
            "empty": {"type": "array"},
            "mixed": {"type": "array"},
            "owner": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}},
                },
            },
        },
    }
    assert "required" not in schema
    assert "additionalProperties" not in schema


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (
            ExampleOutputJsonSource(
                file_id=UUID(int=1),
                is_json=True,
                content='{"decision":"yes"}',
                content_complete=False,
            ),
            "incomplete_content",
        ),
        (
            ExampleOutputJsonSource(
                file_id=UUID(int=1),
                is_json=True,
                content='{"decision":',
                content_complete=True,
            ),
            "invalid_json",
        ),
        (
            ExampleOutputJsonSource(
                file_id=UUID(int=1),
                is_json=True,
                content='["not", "an", "object"]',
                content_complete=True,
            ),
            "top_level_not_object",
        ),
        (
            ExampleOutputJsonSource(
                file_id=UUID(int=1),
                is_json=True,
                content='{"value":"' + ("x" * EXAMPLE_OUTPUT_MAX_JSON_BYTES) + '"}',
                content_complete=True,
            ),
            "raw_bytes",
        ),
        (
            ExampleOutputJsonSource(
                file_id=UUID(int=1),
                is_json=True,
                content=(
                    "{"
                    + ",".join(
                        f'"field_{index}":{index}'
                        for index in range(EXAMPLE_OUTPUT_MAX_FIELDS + 1)
                    )
                    + "}"
                ),
                content_complete=True,
            ),
            "field_count",
        ),
        (
            ExampleOutputJsonSource(
                file_id=UUID(int=1),
                is_json=True,
                content=(
                    '{"root":'
                    + ('{"nested":' * EXAMPLE_OUTPUT_MAX_DEPTH)
                    + '"value"'
                    + ("}" * EXAMPLE_OUTPUT_MAX_DEPTH)
                    + "}"
                ),
                content_complete=True,
            ),
            "depth",
        ),
    ],
)
def test_example_output_inference_declines_unsafe_content_with_typed_reason(
    source: ExampleOutputJsonSource,
    reason: str,
) -> None:
    resolution = resolve_example_output_schema_inference(
        sources=(source,),
        authoritative_evidence=None,
    )

    assert resolution.evidence is None
    assert resolution.outcome is not None
    assert resolution.outcome.status == "not_inferred"
    assert resolution.outcome.reason == reason
    assert resolution.outcome.source_file_ids == [source.file_id]


def test_example_output_inference_ignores_non_json_examples() -> None:
    source = ExampleOutputJsonSource(
        file_id=UUID(int=1),
        is_json=False,
        content="Decision\nApproved",
        content_complete=True,
    )

    resolution = resolve_example_output_schema_inference(
        sources=(source,),
        authoritative_evidence=None,
    )

    assert resolution.evidence is None
    assert resolution.outcome is not None
    assert resolution.outcome.status == "not_inferred"
    assert resolution.outcome.reason == "no_json_object"


def test_example_output_inference_merges_equal_shapes_and_declines_conflicts() -> None:
    first = ExampleOutputJsonSource(
        file_id=UUID(int=1),
        is_json=True,
        content='{"decision":"yes","count":1}',
        content_complete=True,
    )
    equivalent = ExampleOutputJsonSource(
        file_id=UUID(int=2),
        is_json=True,
        content='{"count":4,"decision":"no"}',
        content_complete=True,
    )
    conflicting = ExampleOutputJsonSource(
        file_id=UUID(int=3),
        is_json=True,
        content='{"summary":"different"}',
        content_complete=True,
    )

    merged = resolve_example_output_schema_inference(
        sources=(first, equivalent),
        authoritative_evidence=None,
    )
    conflict = resolve_example_output_schema_inference(
        sources=(first, conflicting),
        authoritative_evidence=None,
    )

    assert merged.evidence is not None
    assert merged.evidence.source_file_ids == [first.file_id, equivalent.file_id]
    assert merged.outcome is not None
    assert merged.outcome.status == "inferred"
    assert conflict.evidence is None
    assert conflict.outcome is not None
    assert conflict.outcome.status == "not_inferred"
    assert conflict.outcome.reason == "conflicting_shapes"


def test_example_output_field_bound_counts_inferred_shape_not_repeated_items() -> None:
    source = ExampleOutputJsonSource(
        file_id=UUID(int=1),
        is_json=True,
        content='{"items":['
        + ",".join('{"decision":"approved"}' for _ in range(101))
        + "]}",
        content_complete=True,
    )

    resolution = resolve_example_output_schema_inference(
        sources=(source,),
        authoritative_evidence=None,
    )

    assert resolution.evidence is not None
    assert resolution.evidence.json_schema["properties"] == {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"decision": {"type": "string"}},
            },
        }
    }


def test_higher_priority_schema_prevents_example_shape_inference() -> None:
    explicit = build_output_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"approved": {"type": "boolean"}},
        },
        source="freeform_text",
        confidence="high",
        evidence=("message:1",),
    )
    source = ExampleOutputJsonSource(
        file_id=UUID(int=1),
        is_json=True,
        content='{"decision":"yes"}',
        content_complete=True,
    )

    resolution = resolve_example_output_schema_inference(
        sources=(source,),
        authoritative_evidence=explicit,
    )

    assert resolution.evidence is explicit
    assert resolution.outcome is not None
    assert resolution.outcome.status == "not_inferred"
    assert resolution.outcome.reason == "higher_priority_schema"
