from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder import ai_builder_conversation_metadata as metadata_module
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    CLASSIFIER_RETENTION_CLASSES,
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
    question_interaction_id_from_metadata,
    question_response_from_metadata,
    question_response_to_metadata,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    requirements_summary_to_metadata,
    slot_classification_from_metadata,
    slot_classification_metadata_from_result,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedEvidence,
    ClassifiedFileRole,
    ClassifiedFormIntake,
    ClassifiedSlot,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import LLM_RESOLVABLE_SLOT_NAMES
from eneo.flows.ai_builder.planning_state import (
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSourceCoverage,
    ExampleOutputStyleConstraint,
)
from eneo.flows.ai_builder.planning_state_builder import (
    CLASSIFIER_REBUILD_INPUT_CLASSES,
)

_AI_BUILDER_SRC = (
    Path(__file__).resolve().parents[4] / "src" / "eneo" / "flows" / "ai_builder"
)
_CLASSIFICATION_SOURCE_ID = "user_message:user-1"
_ATTACHMENT_EVIDENCE_FINGERPRINT = "f" * 64


def _classified_evidence(quote: str) -> ClassifiedEvidence:
    return ClassifiedEvidence(source_id=_CLASSIFICATION_SOURCE_ID, quote=quote)


def _classification_input(*quotes: str) -> SlotClassificationInput:
    return SlotClassificationInput(
        sources=(
            SlotClassificationSource(
                source_id=_CLASSIFICATION_SOURCE_ID,
                kind="user_message",
                text="\n".join(quotes),
                message_id="user-1",
            ),
        )
    )


def _persisted_classification_header() -> dict[str, object]:
    return {
        "schema_version": 14,
        "prompt_hash": "a" * 64,
        "model": "openai/gpt-test",
        "provider": "openai",
        "source_inventory": [
            {
                "source_id": _CLASSIFICATION_SOURCE_ID,
                "kind": "user_message",
                "source_sha256": "b" * 64,
                "message_id": "user-1",
            }
        ],
    }


def _capture_metadata_warnings(monkeypatch) -> list[tuple[str, dict[str, object]]]:
    warnings: list[tuple[str, dict[str, object]]] = []

    def capture_warning(
        message: str, *, extra: dict[str, object] | None = None
    ) -> None:
        warnings.append((message, extra or {}))

    monkeypatch.setattr(metadata_module.logger, "warning", capture_warning)
    return warnings


def test_question_answer_request_discriminator_is_not_persisted() -> None:
    metadata = metadata_for_user_message(
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "primary_runtime_input",
            "selected_option_id": "documents",
            "selected_value": "documents",
            "ui_language": "sv",
        },
        ui_language="sv",
    )

    assert metadata == {
        "question_answer": {
            "question_id": "primary_runtime_input",
            "selected_option_id": "documents",
            "selected_value": "documents",
        },
        "ui_language": "sv",
    }
    answer = question_answer_from_metadata(metadata)
    assert answer is not None
    assert question_answer_question_id(answer) == "primary_runtime_input"


def test_question_response_metadata_round_trips_canonical_question_identity() -> None:
    metadata = question_response_to_metadata("final_output_mode")

    assert metadata == {"question_response": {"question_id": "terminal_output"}}
    response = question_response_from_metadata(metadata)
    assert response is not None
    assert response.question_id == "terminal_output"


def test_question_response_metadata_rejects_empty_persisted_identity(
    monkeypatch,
) -> None:
    warnings = _capture_metadata_warnings(monkeypatch)

    assert (
        question_response_from_metadata({"question_response": {"question_id": ""}})
        is None
    )
    assert warnings[0][1]["metadata_kind"] == "question_response"


def test_question_response_metadata_rejects_unsupported_persisted_identity(
    monkeypatch,
) -> None:
    warnings = _capture_metadata_warnings(monkeypatch)

    assert (
        question_response_from_metadata(
            {"question_response": {"question_id": "invented_question"}}
        )
        is None
    )
    assert warnings[0][1]["metadata_kind"] == "question_response"


def test_question_response_writer_rejects_unsupported_question_identity() -> None:
    with pytest.raises(ValidationError):
        question_response_to_metadata("invented_question")


def test_question_interaction_identity_prefers_explicit_answer() -> None:
    assert (
        question_interaction_id_from_metadata(
            {
                "question_answer": {
                    "question_id": "primary_runtime_input",
                    "selected_value": "documents",
                },
                "question_response": {"question_id": "terminal_output"},
            }
        )
        == "primary_runtime_input"
    )


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
        ),
        attachment_evidence_fingerprint=_ATTACHMENT_EVIDENCE_FINGERPRINT,
    )

    parsed = requirements_summary_from_metadata(metadata)

    assert metadata["requirements_version"] == "req_1"
    assert (
        metadata["attachment_evidence_fingerprint"] == _ATTACHMENT_EVIDENCE_FINGERPRINT
    )
    assert parsed is not None
    assert parsed.requirements_version == "req_1"
    assert parsed.attachment_evidence_fingerprint == _ATTACHMENT_EVIDENCE_FINGERPRINT
    assert parsed.requirements_summary.summary == "Build a document summary flow."


def test_requirements_summary_metadata_requires_attachment_fingerprint(
    monkeypatch,
) -> None:
    warnings = _capture_metadata_warnings(monkeypatch)
    payload = RequirementsSummaryPayload(
        requirements_version="req_1",
        summary="Build a document summary flow.",
        key_decisions=[],
        input_description="Uploaded documents.",
        output_description="A concise summary.",
    )

    parsed = requirements_summary_from_metadata(
        {
            "requirements_summary": payload.model_dump(mode="json"),
            "requirements_version": "req_1",
        }
    )

    assert parsed is None
    assert warnings
    assert warnings[0][1]["metadata_kind"] == "requirements_summary"


def test_slot_classification_round_trips_all_llm_resolvable_slots() -> None:
    file_id = uuid4()
    values_by_slot = {
        "primary_runtime_input": "documents",
        "terminal_output": "structured_text",
        "document_material_scope": "flexible_document_case",
        "report_disposition": "per_source_sections",
        "post_processing_goal": "summarize_or_overview",
        "structured_io_contract": "extract_or_compute_fields",
        "runtime_metadata_fields": "detailed_case_metadata",
    }
    result = SlotClassificationResult(
        slots=tuple(
            ClassifiedSlot(
                slot_name=slot_name,
                value=value,
                confidence="high",
                reason=f"{slot_name} evidence",
                evidence=(_classified_evidence(f"{slot_name} quote"),),
                evidence_level="explicit",
            )
            for slot_name, value in values_by_slot.items()
        ),
        form_intake=ClassifiedFormIntake(
            needs_form_fields=True,
            sectioned_form_intake=True,
            confidence="high",
            reason="runtime text per section",
            evidence=(_classified_evidence("fritext under varje rubrik"),),
            evidence_level="explicit",
        ),
        file_roles=(
            ClassifiedFileRole(
                file_id=file_id,
                role="template",
                confidence="high",
                reason="user identifies the file as a template",
                evidence=(_classified_evidence("use the attached template"),),
                evidence_level="explicit",
            ),
        ),
        secondary_obligations=("risks", "actions"),
        assumptions=("User wants runtime form fields.",),
        contradictions=("No contradiction.",),
    )

    classification = slot_classification_metadata_from_result(
        result,
        prompt_hash="a" * 64,
        classification_input=SlotClassificationInput(
            sources=(
                SlotClassificationSource(
                    source_id=_CLASSIFICATION_SOURCE_ID,
                    kind="user_message",
                    text="\n".join(
                        [
                            *(f"{slot_name} quote" for slot_name in values_by_slot),
                            "fritext under varje rubrik",
                            "use the attached template",
                        ]
                    ),
                    message_id="user-1",
                ),
                SlotClassificationSource(
                    source_id=f"uploaded_file:{file_id}",
                    kind="uploaded_file",
                    text="filename: template.docx",
                    file_id=file_id,
                    coverage="fully_seen",
                ),
            )
        ),
        model="openai/gpt-test",
        provider="openai",
    )
    metadata = metadata_with_slot_classification(None, classification)
    parsed = slot_classification_from_metadata(metadata)

    assert classification is not None
    assert parsed is not None
    assert {slot.slot_name for slot in parsed.slots} == LLM_RESOLVABLE_SLOT_NAMES
    assert set(get_args(LLMResolvableSlotName)) == LLM_RESOLVABLE_SLOT_NAMES
    assert parsed.to_result().slots == result.slots
    assert parsed.to_result().form_intake == result.form_intake
    assert parsed.to_result().file_roles == result.file_roles
    assert parsed.to_result().secondary_obligations == ("risks", "actions")
    assert parsed.model == "openai/gpt-test"
    assert parsed.provider == "openai"
    assert parsed.source_inventory[0].source_id == _CLASSIFICATION_SOURCE_ID


def test_classifier_rebuild_classes_all_have_canonical_retention_rules() -> None:
    assert CLASSIFIER_REBUILD_INPUT_CLASSES == CLASSIFIER_RETENTION_CLASSES


def test_classifier_metadata_rejects_attachment_only_terminal_output() -> None:
    file_id = uuid4()
    source_id = f"uploaded_file:{file_id}"

    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_json",
                    confidence="medium",
                    reason="the attachment contains JSON",
                    evidence=(
                        ClassifiedEvidence(source_id=source_id, quote='{"id": 1}'),
                    ),
                    evidence_level="inferred",
                ),
            )
        ),
        prompt_hash="a" * 64,
        classification_input=SlotClassificationInput(
            sources=(
                SlotClassificationSource(
                    source_id=source_id,
                    kind="uploaded_file",
                    text='{"id": 1}',
                    file_id=file_id,
                    coverage="fully_seen",
                ),
            )
        ),
        model="openai/gpt-test",
        provider="openai",
    )

    assert classification is None


def test_classifier_retention_identities_follow_replay_confidence_rules() -> None:
    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_text",
                    confidence="low",
                    reason="not effective",
                    evidence=(_classified_evidence("weak output guess"),),
                ),
                ClassifiedSlot(
                    slot_name="primary_runtime_input",
                    value="unknown",
                    confidence="low",
                    reason="explicit clearing result",
                    evidence=(),
                ),
            ),
            assumptions=("diagnostic note",),
            contradictions=("another diagnostic note",),
        ),
        prompt_hash="a" * 64,
        classification_input=_classification_input("weak output guess"),
        model="openai/gpt-test",
        provider="openai",
    )

    assert classification is not None
    assert classification.effective_retention_identities() == frozenset(
        {("slot", "primary_runtime_input")}
    )


def test_example_output_constraints_round_trip_with_replay_sources() -> None:
    file_id = uuid4()
    file_source_id = f"uploaded_file:{file_id}"
    constraints = ExampleOutputConstraintEvidence(
        source_file_ids=[file_id],
        source_coverage=[
            ExampleOutputSourceCoverage(file_id=file_id, coverage="fully_seen")
        ],
        headings=["Summary", "Decision"],
        style_constraints=[
            ExampleOutputStyleConstraint(
                category="tone",
                description="Formal and concise",
            )
        ],
        confidence="high",
        citations=[
            ExampleOutputCitation(
                source_id=file_source_id,
                file_id=file_id,
                quote="# Summary",
            ),
            ExampleOutputCitation(
                source_id=_CLASSIFICATION_SOURCE_ID,
                quote="Use this as the output example.",
            ),
        ],
    )
    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(example_output_constraints=constraints),
        prompt_hash="a" * 64,
        classification_input=SlotClassificationInput(
            sources=(
                SlotClassificationSource(
                    source_id=_CLASSIFICATION_SOURCE_ID,
                    kind="user_message",
                    text="Use this as the output example.",
                    message_id="user-1",
                ),
                SlotClassificationSource(
                    source_id=file_source_id,
                    kind="uploaded_file",
                    text="# Summary",
                    file_id=file_id,
                    coverage="fully_seen",
                ),
            )
        ),
        model="openai/gpt-test",
        provider="openai",
    )

    assert classification is not None
    metadata = metadata_with_slot_classification(None, classification)
    parsed = slot_classification_from_metadata(metadata)
    assert parsed is not None
    assert parsed.to_result().example_output_constraints == constraints
    assert parsed.effective_retention_identities() == frozenset(
        {("example_output_constraint", "current")}
    )
    retained = parsed.retain_effective_semantics(
        frozenset({("example_output_constraint", "current")})
    )
    assert retained.example_output_constraints == constraints
    assert {source.source_id for source in retained.source_inventory} == {
        _CLASSIFICATION_SOURCE_ID,
        file_source_id,
    }


def test_example_output_constraint_metadata_rejects_citation_file_mismatch() -> None:
    file_id = uuid4()
    different_file_id = uuid4()
    file_source_id = f"uploaded_file:{file_id}"
    payload = {
        **_persisted_classification_header(),
        "source_inventory": [
            {
                "source_id": file_source_id,
                "kind": "uploaded_file",
                "source_sha256": "b" * 64,
                "file_id": str(file_id),
                "coverage": "fully_seen",
            }
        ],
        "slots": [],
        "example_output_constraints": {
            "source_file_ids": [str(file_id)],
            "source_coverage": [{"file_id": str(file_id), "coverage": "fully_seen"}],
            "headings": ["Summary"],
            "style_constraints": [],
            "confidence": "medium",
            "citations": [
                {
                    "source_id": file_source_id,
                    "file_id": str(different_file_id),
                    "quote": "# Summary",
                }
            ],
        },
    }

    assert slot_classification_from_metadata({"slot_classification": payload}) is None


def test_slot_classification_metadata_rejects_extra_nested_fields() -> None:
    assert (
        slot_classification_from_metadata(
            {
                "slot_classification": {
                    **_persisted_classification_header(),
                    "slots": [
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "high",
                            "reason": "report output",
                            "evidence": [
                                {
                                    "source_id": _CLASSIFICATION_SOURCE_ID,
                                    "quote": "user asked for a report",
                                }
                            ],
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
                    **_persisted_classification_header(),
                    "slots": [
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "high",
                            "reason": "x" * 501,
                            "evidence": [
                                {
                                    "source_id": _CLASSIFICATION_SOURCE_ID,
                                    "quote": "user asked for a report",
                                }
                            ],
                        }
                    ],
                }
            }
        )
        is None
    )


def test_slot_classification_metadata_logs_invalid_persisted_shape(monkeypatch) -> None:
    warnings = _capture_metadata_warnings(monkeypatch)

    assert (
        slot_classification_from_metadata(
            {
                "slot_classification": {
                    **_persisted_classification_header(),
                    "slots": [
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "high",
                            "reason": "x" * 501,
                            "evidence": [
                                {
                                    "source_id": _CLASSIFICATION_SOURCE_ID,
                                    "quote": "user asked for a report",
                                }
                            ],
                        }
                    ],
                }
            }
        )
        is None
    )

    assert warnings
    message, extra = warnings[0]
    assert message == "AI Builder ignored invalid persisted conversation metadata"
    assert extra["metadata_kind"] == "slot_classification"


def test_slot_classification_metadata_rejects_versionless_preproduction_shape(
    monkeypatch,
) -> None:
    warnings = _capture_metadata_warnings(monkeypatch)
    payload = _persisted_classification_header()
    del payload["schema_version"]
    payload["slots"] = []

    assert slot_classification_from_metadata({"slot_classification": payload}) is None
    assert warnings
    validation_errors = warnings[0][1]["validation_errors"]
    assert isinstance(validation_errors, list)
    assert any(error.get("loc") == ("schema_version",) for error in validation_errors)


def test_slot_classification_metadata_rejects_incomplete_typed_source_identity() -> (
    None
):
    incomplete_sources = [
        {
            "source_id": "structured_answer:user-1:0",
            "kind": "structured_answer",
            "source_sha256": "b" * 64,
            "message_id": "user-1",
            "question_id": "terminal_output",
        },
        {
            "source_id": f"uploaded_file:{uuid4()}",
            "kind": "uploaded_file",
            "source_sha256": "b" * 64,
            "file_id": str(uuid4()),
        },
    ]

    for source in incomplete_sources:
        payload = {
            **_persisted_classification_header(),
            "source_inventory": [source],
            "slots": [],
        }
        assert (
            slot_classification_from_metadata({"slot_classification": payload}) is None
        )


def test_requirements_summary_metadata_logs_invalid_persisted_shape(
    monkeypatch,
) -> None:
    warnings = _capture_metadata_warnings(monkeypatch)

    assert (
        requirements_summary_from_metadata(
            {
                "requirements_summary": {
                    "summary_markdown": "missing required version field"
                },
                "requirements_version": "req_1",
            }
        )
        is None
    )

    assert warnings
    message, extra = warnings[0]
    assert message == "AI Builder ignored invalid persisted conversation metadata"
    assert extra["metadata_kind"] == "requirements_summary"


def test_slot_classification_metadata_rejects_missing_evidence() -> None:
    assert (
        slot_classification_from_metadata(
            {
                "slot_classification": {
                    **_persisted_classification_header(),
                    "slots": [
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "high",
                            "reason": "old unsupported shape",
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
                    evidence=(_classified_evidence("user asked for a report"),),
                ),
            )
        ),
        prompt_hash="a" * 64,
        classification_input=_classification_input("user asked for a report"),
        model="openai/gpt-test",
        provider="openai",
    )

    assert classification is not None
    assert len(classification.slots[0].reason) == 500
    assert classification.slots[0].evidence[0].model_dump() == {
        "source_id": _CLASSIFICATION_SOURCE_ID,
        "quote": "user asked for a report",
    }


def test_slot_classification_writer_filters_invalid_and_keeps_low_diagnostic() -> None:
    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_text",
                    confidence="high",
                    reason="valid",
                    evidence=(_classified_evidence("valid quote"),),
                ),
                ClassifiedSlot(
                    slot_name="runtime_metadata_fields",
                    value="not_a_runtime_metadata_value",
                    confidence="high",
                    reason="invalid",
                    evidence=(_classified_evidence("invalid quote"),),
                ),
                ClassifiedSlot(
                    slot_name="primary_runtime_input",
                    value="unknown",
                    confidence="low",
                    reason="retained for negative calibration",
                    evidence=(_classified_evidence("uncertain quote"),),
                ),
            )
        ),
        prompt_hash="a" * 64,
        classification_input=_classification_input(
            "valid quote",
            "invalid quote",
            "uncertain quote",
        ),
        model="openai/gpt-test",
        provider="openai",
    )

    assert classification is not None
    assert [slot.slot_name for slot in classification.slots] == [
        "terminal_output",
        "primary_runtime_input",
    ]


def test_slot_classification_writer_keeps_first_duplicate_slot() -> None:
    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_text",
                    confidence="high",
                    reason="first valid slot",
                    evidence=(_classified_evidence("first quote"),),
                ),
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_json",
                    confidence="high",
                    reason="duplicate valid slot",
                    evidence=(_classified_evidence("second quote"),),
                ),
            )
        ),
        prompt_hash="a" * 64,
        classification_input=_classification_input("first quote", "second quote"),
        model="openai/gpt-test",
        provider="openai",
    )

    assert classification is not None
    assert [(slot.slot_name, slot.value) for slot in classification.slots] == [
        ("terminal_output", "structured_text")
    ]


def test_slot_classification_model_rejects_duplicate_slots() -> None:
    metadata = {
        **_persisted_classification_header(),
        "slots": [
            {
                "slot_name": "terminal_output",
                "value": "structured_text",
                "confidence": "high",
                "reason": "first",
                "evidence": [
                    {
                        "source_id": _CLASSIFICATION_SOURCE_ID,
                        "quote": "first quote",
                    }
                ],
            },
            {
                "slot_name": "terminal_output",
                "value": "structured_json",
                "confidence": "high",
                "reason": "second",
                "evidence": [
                    {
                        "source_id": _CLASSIFICATION_SOURCE_ID,
                        "quote": "second quote",
                    }
                ],
            },
        ],
    }

    assert slot_classification_from_metadata({"slot_classification": metadata}) is None


def test_slot_classification_model_rejects_non_llm_slot_name() -> None:
    assert (
        slot_classification_from_metadata(
            {
                "slot_classification": {
                    **_persisted_classification_header(),
                    "slots": [
                        {
                            "slot_name": "docx_output_mode",
                            "value": "generated_docx",
                            "confidence": "high",
                            "reason": "not LLM resolvable",
                            "evidence": [
                                {
                                    "source_id": _CLASSIFICATION_SOURCE_ID,
                                    "quote": "not LLM resolvable quote",
                                }
                            ],
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
