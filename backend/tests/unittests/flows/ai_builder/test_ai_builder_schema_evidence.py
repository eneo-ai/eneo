from __future__ import annotations

import json
from uuid import UUID

import pytest

from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentSchemaDiscovery,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    validate_preprovider_schema_gate,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    EXAMPLE_OUTPUT_MAX_DEPTH,
    EXAMPLE_OUTPUT_MAX_FIELDS,
    EXAMPLE_OUTPUT_MAX_JSON_BYTES,
    SCHEMA_CANDIDATE_MAX_ITEMS,
    SCHEMA_MAX_JSON_BYTES,
    SCHEMA_PROVENANCE_MAX_ITEMS,
    DeclaredSchemaCandidate,
    ExampleOutputJsonSource,
    SchemaLimitExceeded,
    build_declared_schema_candidate,
    build_schema_evidence,
    declared_candidate_evidence,
    parse_schema_candidate,
    resolve_example_output_schema_inference,
    resolve_structured_schema_direction,
    schema_direction_option_values,
)


def _candidate(
    field: str,
    file_number: int,
) -> DeclaredSchemaCandidate:
    file_id = UUID(int=file_number)
    return build_declared_schema_candidate(
        {"type": "object", "properties": {field: {"type": "string"}}},
        source_file_ids=(file_id,),
        provenance=(f"file:{file_id}:json_schema_attachment",),
    )


def _selection_conversation(
    candidates: tuple[DeclaredSchemaCandidate, ...],
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
                        "question_id": "schema_direction",
                        "question": "Which schema?",
                        "options": options
                        if options is not None
                        else [
                            {
                                "id": value,
                                "label": value,
                                "value": value,
                            }
                            for value in schema_direction_option_values(candidates)
                        ],
                        "selection_mode": "multi",
                        "allow_custom": False,
                        "requires_confirm": True,
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
            message_id="user-2",
            role="user",
            content="Use the selected schema.",
            metadata={
                "question_answer": {
                    "question_id": "schema_direction",
                    "selected_values": selected_values,
                }
            },
        ),
    ]


def test_declared_candidate_fails_instead_of_truncating_provenance() -> None:
    provenance = tuple(
        f"message:user-{index}:fenced_json_schema"
        for index in range(SCHEMA_PROVENANCE_MAX_ITEMS + 1)
    )

    with pytest.raises(ValueError, match="provenance item limit"):
        build_declared_schema_candidate(
            {"type": "object", "properties": {}},
            provenance=provenance,
        )


def test_declared_assignment_fails_instead_of_truncating_combined_evidence() -> None:
    candidate = build_declared_schema_candidate(
        {"type": "object", "properties": {}},
        provenance=tuple(
            f"message:user-{index}:fenced_json_schema"
            for index in range(SCHEMA_PROVENANCE_MAX_ITEMS)
        ),
    )

    with pytest.raises(ValueError, match="schema direction evidence"):
        declared_candidate_evidence(
            candidate,
            confidence="high",
            assignment_evidence=("quote:user_message:user-final:use as input",),
        )


def _schema_fence(index: int) -> str:
    return (
        "```json\n"
        + json.dumps(
            {
                "type": "object",
                "properties": {f"conversation_{index}": {"type": "string"}},
            }
        )
        + "\n```"
    )


def _attachment_schema_candidates(count: int) -> tuple[DeclaredSchemaCandidate, ...]:
    return tuple(
        build_declared_schema_candidate(
            {
                "type": "object",
                "properties": {f"attachment_{index}": {"type": "string"}},
            },
            provenance=(f"file:{UUID(int=index + 1)}:json_schema_attachment",),
        )
        for index in range(count)
    )


def _schema_candidate_context(count: int) -> AIBuilderAttachmentContext:
    return AIBuilderAttachmentContext(
        context=None,
        evidence=(),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
        schema_discovery=AIBuilderAttachmentSchemaDiscovery(
            candidates=_attachment_schema_candidates(count),
        ),
    )


def test_combined_candidate_set_accepts_exactly_one_hundred() -> None:
    conversation = [
        ConversationMessage(
            message_id="user-many",
            role="user",
            content="\n".join(_schema_fence(index) for index in range(50)),
        )
    ]

    validate_preprovider_schema_gate(
        conversation=conversation,
        attachment_context=_schema_candidate_context(50),
    )


def test_combined_candidate_set_rejects_overflow_before_provider() -> None:
    conversation = [
        ConversationMessage(
            message_id="user-many",
            role="user",
            content="\n".join(_schema_fence(index) for index in range(51)),
        )
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        validate_preprovider_schema_gate(
            conversation=conversation,
            attachment_context=_schema_candidate_context(50),
        )

    assert exc_info.value.code is AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED
    assert exc_info.value.context == {
        "reason": "candidate_count",
        "max_value": SCHEMA_CANDIDATE_MAX_ITEMS,
        "actual_value": SCHEMA_CANDIDATE_MAX_ITEMS + 1,
    }


def test_preprovider_gate_rejects_assignment_after_candidate_set_changes() -> None:
    offered = _candidate("old_field", 701)
    current = _candidate("current_field", 702)
    conversation = _selection_conversation(
        (offered,),
        selected_values=[f"input:{offered.fingerprint}"],
    )
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        evidence=(),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
        schema_discovery=AIBuilderAttachmentSchemaDiscovery(candidates=(current,)),
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        validate_preprovider_schema_gate(
            conversation=conversation,
            attachment_context=attachment_context,
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "invalid_schema_direction"}


def test_oversized_generic_json_fence_is_not_misreported_as_schema() -> None:
    conversation = [
        ConversationMessage(
            message_id="user-large-json",
            role="user",
            content='```json\n{"records":"' + ("😀" * 33_000) + '"}\n```',
        )
    ]

    validate_preprovider_schema_gate(
        conversation=conversation,
        attachment_context=None,
    )


def test_oversized_explicit_json_schema_fence_remains_blocking() -> None:
    conversation = [
        ConversationMessage(
            message_id="user-large-schema",
            role="user",
            content='```jsonschema\n{"description":"' + ("😀" * 33_000) + '"}\n```',
        )
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        validate_preprovider_schema_gate(
            conversation=conversation,
            attachment_context=None,
        )

    assert exc_info.value.code is AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED
    assert exc_info.value.context["reason"] == "raw_bytes"


@pytest.mark.parametrize(
    "constant",
    ["NaN", "Infinity", "-Infinity", "1e309"],
)
def test_explicit_schema_parser_rejects_non_finite_numbers(constant: str) -> None:
    assert (
        parse_schema_candidate(
            '{"type":"object","properties":{},"default":' + constant + "}"
        )
        is None
    )


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_schema_evidence_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        build_schema_evidence(
            json_schema={"type": "object", "default": value},
            source="declared_schema",
            confidence="high",
            evidence=("message:invalid-schema",),
        )


def test_explicit_schema_parser_preserves_canonical_size_failure() -> None:
    raw_json = (
        '{"type":"object","allOf":['
        + ",".join('{"default":1e9}' for _ in range(5_500))
        + "]}"
    )
    assert len(raw_json.encode("utf-8")) < SCHEMA_MAX_JSON_BYTES

    with pytest.raises(SchemaLimitExceeded) as exc_info:
        parse_schema_candidate(raw_json)

    assert exc_info.value.reason == "canonical_bytes"
    assert exc_info.value.actual_value is not None
    assert exc_info.value.actual_value > SCHEMA_MAX_JSON_BYTES


def test_selection_requires_exact_current_candidate_set() -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)
    conversation = _selection_conversation(
        (first, second),
        selected_values=[f"output:{second.fingerprint}"],
    )

    selected = resolve_structured_schema_direction(
        conversation=conversation,
        candidates=(first, second),
    )
    drifted = resolve_structured_schema_direction(
        conversation=conversation,
        candidates=(first, second, _candidate("added", 3)),
    )

    assert selected is not None
    assert selected.output_fingerprint == second.fingerprint
    assert selected.confidence == "high"
    assert selected.evidence == (
        f"quote:structured_answer:user-2:0:output:{second.fingerprint}",
    )
    assert drifted is None


def test_stale_schema_direction_answer_records_discard_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)
    conversation = _selection_conversation(
        (first,),
        selected_values=[f"output:{first.fingerprint}"],
    )

    with caplog.at_level(
        "INFO",
        logger="eneo.flows.ai_builder.ai_builder_schema_evidence",
    ):
        selected = resolve_structured_schema_direction(
            conversation=conversation,
            candidates=(first, second),
        )

    assert selected is None
    record = next(
        record
        for record in caplog.records
        if record.message == "AI Builder discarded schema-direction answer"
    )
    assert record.message_id == "user-2"
    assert record.discard_reason == "candidate_set_changed"


def test_selection_allows_one_schema_on_both_boundaries() -> None:
    candidate = _candidate("shared", 1)

    selected = resolve_structured_schema_direction(
        conversation=_selection_conversation(
            (candidate,),
            selected_values=[
                f"input:{candidate.fingerprint}",
                f"output:{candidate.fingerprint}",
            ],
        ),
        candidates=(candidate,),
    )

    assert selected is not None
    assert selected.input_fingerprint == candidate.fingerprint
    assert selected.output_fingerprint == candidate.fingerprint
    assert selected.reference_only is False


def test_selection_can_leave_all_candidates_as_reference_only() -> None:
    candidates = (_candidate("decision", 1), _candidate("count", 2))

    selected = resolve_structured_schema_direction(
        conversation=_selection_conversation(
            candidates,
            selected_values=["reference_only"],
        ),
        candidates=candidates,
    )

    assert selected is not None
    assert selected.input_fingerprint is None
    assert selected.output_fingerprint is None
    assert selected.reference_only is True


def test_selection_rejects_valid_fingerprint_plus_spoofed_extra() -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)

    resolution = resolve_structured_schema_direction(
        conversation=_selection_conversation(
            (first, second),
            selected_values=[f"output:{second.fingerprint}", "spoofed"],
        ),
        candidates=(first, second),
    )

    assert resolution is None


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

    resolution = resolve_structured_schema_direction(
        conversation=_selection_conversation(
            (first, second),
            selected_values=[f"output:{second.fingerprint}"],
            options=options,
        ),
        candidates=(first, second),
    )

    assert resolution is None


def test_selection_ignores_question_payload_on_wrong_tool() -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)

    resolution = resolve_structured_schema_direction(
        conversation=_selection_conversation(
            (first, second),
            selected_values=[f"output:{second.fingerprint}"],
            tool_name="propose_flow",
        ),
        candidates=(first, second),
    )

    assert resolution is None


def test_selection_fails_closed_for_non_json_persisted_arguments() -> None:
    first = _candidate("decision", 1)
    second = _candidate("count", 2)

    resolution = resolve_structured_schema_direction(
        conversation=_selection_conversation(
            (first, second),
            selected_values=[f"output:{second.fingerprint}"],
            options=[
                {
                    "id": second.fingerprint,
                    "value": object(),
                }
            ],
        ),
        candidates=(first, second),
    )

    assert resolution is None


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
    explicit = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"approved": {"type": "boolean"}},
        },
        source="declared_schema",
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
