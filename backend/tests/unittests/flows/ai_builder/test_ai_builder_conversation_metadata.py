from __future__ import annotations

import re
from pathlib import Path

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_for_user_message,
    question_answer_from_metadata,
    question_answer_question_id,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    requirements_summary_to_metadata,
    tool_calls_from_message,
)

_AI_BUILDER_SRC = (
    Path(__file__).resolve().parents[4] / "src" / "intric" / "flows" / "ai_builder"
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


def test_requirements_summary_round_trips_through_canonical_metadata() -> None:
    metadata = requirements_summary_to_metadata(
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

    parsed = requirements_summary_from_metadata(metadata)

    assert metadata["requirements_version"] == "req_1"
    assert parsed is not None
    assert parsed.requirements_version == "req_1"
    assert parsed.requirements_summary.summary == "Build a document summary flow."


def test_conversation_metadata_keys_are_not_read_from_scattered_raw_gets() -> None:
    forbidden = re.compile(
        r'metadata\.get\("'
        r"(question_answer|requirements_confirmed|requirements_summary|"
        r'requirements_version|ui_language|file_ids|edit_context)"'
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
            "ai_builder_telemetry.py",
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
