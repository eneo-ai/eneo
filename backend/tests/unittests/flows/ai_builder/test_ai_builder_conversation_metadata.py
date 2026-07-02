from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    PROVIDER_TOOL_CALL_ID_MAX_LENGTH,
    LLMResolvableSlotName,
    loose_tool_call_name,
    loose_tool_call_names_from_message,
    make_persisted_assistant_tool_call,
    metadata_for_user_message,
    metadata_with_slot_classification,
    provider_safe_tool_call_id,
    question_answer_from_metadata,
    question_answer_question_id,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    requirements_summary_to_metadata,
    slot_classification_from_metadata,
    slot_classification_metadata_from_result,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedSlot,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import LLM_RESOLVABLE_SLOT_NAMES

_AI_BUILDER_SRC = (
    Path(__file__).resolve().parents[4] / "src" / "eneo" / "flows" / "ai_builder"
)


def test_question_answer_request_discriminator_is_not_persisted() -> None:
    metadata = metadata_for_user_message(
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "input_material_mode",
            "selected_option_id": "documents",
            "selected_value": "documents",
            "ui_language": "sv",
        },
        ui_language="sv",
    )

    assert metadata == {
        "question_answer": {
            "question_id": "input_material_mode",
            "selected_option_id": "documents",
            "selected_value": "documents",
        },
        "ui_language": "sv",
    }
    answer = question_answer_from_metadata(metadata)
    assert answer is not None
    assert question_answer_question_id(answer) == "input_material_mode"


def test_requirements_confirmation_is_persisted_as_top_level_metadata() -> None:
    metadata = metadata_for_user_message(
        question_answer={
            "kind": "requirements_confirmation",
            "requirements_confirmed": True,
            "requirements_version": "req_1",
        }
    )

    assert metadata == {
        "requirements_confirmed": True,
        "requirements_version": "req_1",
    }
    confirmation = requirements_confirmation_from_metadata(metadata)
    assert confirmation is not None
    assert confirmation.requirements_version == "req_1"


def test_tool_calls_from_message_parses_persisted_json_arguments() -> None:
    (tool_call,) = tool_calls_from_message(
        {
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "ask_structured_question",
                    "arguments": '{"question_id": "runtime_metadata_fields"}',
                }
            ]
        }
    )

    assert tool_call.id == "call_1"
    assert tool_call.name == "ask_structured_question"
    assert tool_call.arguments == {"question_id": "runtime_metadata_fields"}


def test_tool_calls_from_message_ignores_extra_persisted_fields() -> None:
    (tool_call,) = tool_calls_from_message(
        {
            "tool_calls": [
                {
                    "id": "call_legacy",
                    "name": "confirm_requirements",
                    "arguments": {"requirements_version": "req_1"},
                    "legacy_extra": "kept by old rows",
                }
            ]
        }
    )

    assert tool_call.model_dump(mode="json") == {
        "id": "call_legacy",
        "name": "confirm_requirements",
        "arguments": {"requirements_version": "req_1"},
    }


def test_make_persisted_assistant_tool_call_returns_canonical_tool_shape() -> None:
    tool_call = make_persisted_assistant_tool_call(
        tool_call_id="call_2",
        tool_name="confirm_requirements",
    )

    assert tool_call.model_dump(mode="json") == {
        "id": "call_2",
        "name": "confirm_requirements",
        "arguments": {},
    }


def test_tool_calls_from_message_skips_malformed_arguments() -> None:
    assert (
        tool_calls_from_message(
            {
                "tool_calls": [
                    {
                        "id": "call_bad_args",
                        "name": "confirm_requirements",
                        "arguments": "{not json",
                    }
                ]
            }
        )
        == tuple()
    )


def test_loose_tool_call_names_from_message_preserves_legacy_name_only_rows() -> None:
    assert loose_tool_call_names_from_message(
        {
            "tool_calls": [
                {"name": "ask_structured_question"},
                {"id": "call_bad_args", "name": "confirm_requirements"},
                {"name": ""},
                {"name": 123},
            ]
        }
    ) == ("ask_structured_question", "confirm_requirements")


def test_loose_tool_call_name_reads_active_turn_runtime_shape() -> None:
    tool_call = SimpleNamespace(
        function=SimpleNamespace(name="ask_structured_question")
    )

    assert loose_tool_call_name({"name": "confirm_requirements"}) == (
        "confirm_requirements"
    )
    assert loose_tool_call_name(tool_call) == "ask_structured_question"
    assert loose_tool_call_name({"function": {"name": "ignored"}}) is None
    assert loose_tool_call_name(object()) is None


def test_provider_safe_tool_call_id_preserves_valid_ids() -> None:
    tool_call_id = "call_valid_123"

    assert provider_safe_tool_call_id(tool_call_id) == tool_call_id


def test_provider_safe_tool_call_id_maps_legacy_scoped_revision_id() -> None:
    legacy_id = "server_scoped_model_revision:00000000-0000-0000-0000-000000000000"
    assert len(legacy_id) == PROVIDER_TOOL_CALL_ID_MAX_LENGTH + 1

    mapped = provider_safe_tool_call_id(legacy_id)

    assert mapped == provider_safe_tool_call_id(legacy_id)
    assert mapped != legacy_id
    assert len(mapped) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


def test_requirements_summary_round_trips_through_canonical_metadata() -> None:
    metadata = requirements_summary_to_metadata(
        RequirementsSummaryPayload.model_validate(
            {
                "requirements_version": "req_1",
                "summary": "Build a document summary flow.",
                "key_decisions": [
                    {
                        "topic": "input",
                        "decision": "Use uploaded user documents.",
                    }
                ],
                "input_description": "Uploaded documents from the user.",
                "output_description": "A concise summary.",
                "assumptions": ["The user will upload files at runtime."],
            }
        )
    )

    parsed = requirements_summary_from_metadata(metadata)

    assert metadata["requirements_version"] == "req_1"
    assert parsed is not None
    assert parsed.requirements_version == "req_1"
    assert parsed.requirements_summary.summary == "Build a document summary flow."


def test_slot_classification_round_trips_all_llm_resolvable_slots() -> None:
    values_by_slot = {
        "primary_runtime_input": "documents",
        "terminal_output": "structured_text",
        "document_material_scope": "flexible_document_case",
        "post_processing_goal": "summarize_or_overview",
        "structured_io_contract": "extract_or_compute_fields",
        "structured_analysis_need": "use_structured_analysis",
        "runtime_metadata_fields": "detailed_case_metadata",
    }
    result = SlotClassificationResult(
        slots=tuple(
            ClassifiedSlot(
                slot_name=slot_name,
                value=value,
                confidence="high",
                reason=f"{slot_name} evidence",
            )
            for slot_name, value in values_by_slot.items()
        ),
        secondary_obligations=("risks", "actions"),
        assumptions=("User wants runtime form fields.",),
        contradictions=("No contradiction.",),
    )

    classification = slot_classification_metadata_from_result(
        result,
        prompt_hash="a" * 64,
    )
    metadata = metadata_with_slot_classification(None, classification)
    parsed = slot_classification_from_metadata(metadata)

    assert classification is not None
    assert parsed is not None
    assert {slot.slot_name for slot in parsed.slots} == LLM_RESOLVABLE_SLOT_NAMES
    assert set(get_args(LLMResolvableSlotName)) == LLM_RESOLVABLE_SLOT_NAMES
    assert parsed.to_result().slots == result.slots
    assert parsed.to_result().secondary_obligations == ("risks", "actions")


def test_slot_classification_metadata_rejects_extra_nested_fields() -> None:
    assert (
        slot_classification_from_metadata(
            {
                "slot_classification": {
                    "prompt_hash": "a" * 64,
                    "slots": [
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "high",
                            "reason": "report output",
                            "extra": "not persisted",
                        }
                    ],
                }
            }
        )
        is None
    )


def test_slot_classification_metadata_rejects_overlong_reason() -> None:
    assert (
        slot_classification_from_metadata(
            {
                "slot_classification": {
                    "prompt_hash": "a" * 64,
                    "slots": [
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "high",
                            "reason": "x" * 501,
                        }
                    ],
                }
            }
        )
        is None
    )


def test_slot_classification_writer_bounds_reason_text() -> None:
    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_text",
                    confidence="high",
                    reason="x" * 800,
                ),
            )
        ),
        prompt_hash="a" * 64,
    )

    assert classification is not None
    assert len(classification.slots[0].reason) == 500


def test_slot_classification_writer_keeps_valid_slots_when_one_slot_is_invalid() -> (
    None
):
    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_text",
                    confidence="high",
                    reason="valid",
                ),
                ClassifiedSlot(
                    slot_name="runtime_metadata_fields",
                    value="not_a_runtime_metadata_value",
                    confidence="high",
                    reason="invalid",
                ),
                ClassifiedSlot(
                    slot_name="primary_runtime_input",
                    value="unknown",
                    confidence="low",
                    reason="ignored",
                ),
            )
        ),
        prompt_hash="a" * 64,
    )

    assert classification is not None
    assert [slot.slot_name for slot in classification.slots] == ["terminal_output"]


def test_slot_classification_model_rejects_duplicate_slots() -> None:
    metadata = {
        "prompt_hash": "a" * 64,
        "slots": [
            {
                "slot_name": "terminal_output",
                "value": "structured_text",
                "confidence": "high",
                "reason": "first",
            },
            {
                "slot_name": "terminal_output",
                "value": "structured_json",
                "confidence": "high",
                "reason": "second",
            },
        ],
    }

    assert slot_classification_from_metadata({"slot_classification": metadata}) is None


def test_slot_classification_model_rejects_non_llm_slot_name() -> None:
    assert (
        slot_classification_from_metadata(
            {
                "slot_classification": {
                    "prompt_hash": "a" * 64,
                    "slots": [
                        {
                            "slot_name": "docx_output_mode",
                            "value": "generated_docx",
                            "confidence": "high",
                            "reason": "not LLM resolvable",
                        }
                    ],
                }
            }
        )
        is None
    )


def test_conversation_metadata_keys_are_not_read_from_scattered_raw_gets() -> None:
    forbidden = re.compile(
        r'metadata\.get\("'
        r"(question_answer|requirements_confirmed|requirements_summary|"
        r"requirements_version|ui_language|file_ids|edit_context|"
        r'slot_classification)"'
    )
    hits = _source_hits(
        forbidden,
        exclude={"ai_builder_conversation_metadata.py"},
    )

    assert hits == []


def test_persisted_tool_call_fields_are_not_read_from_raw_mappings() -> None:
    forbidden = re.compile(
        r'tool_call(?:_map)?\.get\("(id|name|arguments)"'
        r'|tool_call\["(id|name|arguments)"'
        r'|tool_calls\[.*\]\["(id|name|arguments)"'
    )
    hits = _source_hits(
        forbidden,
        exclude={
            "ai_builder_conversation_metadata.py",
        },
    )

    assert hits == []


def _source_hits(pattern: re.Pattern[str], *, exclude: set[str]) -> list[str]:
    hits: list[str] = []
    for path in sorted(_AI_BUILDER_SRC.glob("*.py")):
        if path.name in exclude:
            continue
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.name}:{line_number}:{line.strip()}")
    return hits
