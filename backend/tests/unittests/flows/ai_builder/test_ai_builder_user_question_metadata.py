from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_for_assistant_question,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)


def _pending_question_conversation(
    question_id: str = "terminal_output",
) -> list[ConversationMessage]:
    return [
        ConversationMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": question_id,
                        "question": "Output?",
                        "options": [
                            {
                                "id": "pdf_document",
                                "label": "PDF",
                                "value": "pdf_document",
                            }
                        ],
                    },
                }
            ],
        )
    ]


def test_free_text_records_only_which_pending_question_the_user_responded_to() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_pending_question_conversation(),
        message="Make it a PDF",
        question_answer=None,
    )

    assert prepared.metadata == {
        "question_response": {"question_id": "terminal_output"}
    }
    assert prepared.metadata is not None
    assert "question_answer" not in prepared.metadata


def test_explicit_ui_answer_is_the_only_source_of_question_answer_metadata() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_pending_question_conversation(),
        message="PDF",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "terminal_output",
            "selected_values": ["pdf_document"],
            "ui_language": "sv",
        },
    )

    assert prepared.metadata == {
        "question_answer": {
            "question_id": "terminal_output",
            "selected_values": ["pdf_document"],
        },
        "ui_language": "sv",
    }


def test_fixed_choice_catalog_question_rejects_custom_answer() -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_pending_question_conversation(),
            message="A spreadsheet",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "terminal_output",
                "custom_value": "spreadsheet",
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "unsupported_question_value"}


def test_mapped_file_limit_accepts_catalog_supported_custom_answer() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_pending_question_conversation("mapped_file_limit"),
        message="3",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "mapped_file_limit",
            "custom_value": "3",
        },
    )

    assert prepared.metadata == {
        "question_answer": {
            "question_id": "mapped_file_limit",
            "custom_value": "3",
        }
    }


def test_non_catalog_fixed_question_rejects_custom_answer() -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_pending_question_conversation("processing_scope"),
            message="Process each department separately",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "processing_scope",
                "custom_value": "separate_departments",
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "unsupported_question_value"}


def test_invalid_schema_direction_selection_is_rejected_before_persistence() -> None:
    first = "a" * 64
    second = "b" * 64
    conversation = [
        ConversationMessage(
            role="assistant",
            content="Assign the schemas.",
            tool_calls=[
                {
                    "id": "schema-direction",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": "schema_direction",
                        "question": "How should the schemas be used?",
                        "options": [
                            {
                                "id": f"input:{first}",
                                "label": "First input",
                                "value": f"input:{first}",
                            },
                            {
                                "id": f"input:{second}",
                                "label": "Second input",
                                "value": f"input:{second}",
                            },
                            {
                                "id": f"output:{first}",
                                "label": "First output",
                                "value": f"output:{first}",
                            },
                            {
                                "id": "reference_only",
                                "label": "Reference only",
                                "value": "reference_only",
                            },
                        ],
                        "selection_mode": "multi",
                        "allow_custom": False,
                        "requires_confirm": True,
                    },
                }
            ],
        )
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="Use both as input.",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "schema_direction",
                "selected_values": [f"input:{first}", f"input:{second}"],
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "invalid_schema_direction"}


def test_free_text_for_non_classifier_question_remains_response_only() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_pending_question_conversation("flow_input_architecture"),
        message="Use one shared input",
        question_answer=None,
    )

    assert prepared.metadata == {
        "question_response": {"question_id": "flow_input_architecture"}
    }
    assert prepared.metadata is not None
    assert "question_answer" not in prepared.metadata


def test_free_text_for_pending_field_details_records_response_only() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_pending_question_conversation("runtime_metadata_field_details"),
        message="Case id",
        question_answer=None,
    )

    assert prepared.metadata == {
        "question_response": {"question_id": "runtime_metadata_field_details"}
    }


def test_runtime_metadata_field_collection_is_accepted_as_a_real_answer() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_pending_question_conversation("runtime_metadata_field_details"),
        message="Case id",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "runtime_metadata_field_details",
            "input_fields": [
                {
                    "value": {"name": "case_id", "label": "Case id"},
                    "purpose": "interpret_input",
                }
            ],
        },
    )

    assert prepared.metadata == {
        "question_answer": {
            "question_id": "runtime_metadata_field_details",
            "input_fields": [
                {
                    "value": {
                        "variable_name": "case_id",
                        "label": "Case id",
                        "field_type": "text",
                        "required": False,
                        "options": [],
                        "provenance": "user_confirmed",
                    },
                    "purpose": "interpret_input",
                }
            ],
        }
    }


def test_answered_question_is_not_attributed_to_later_free_text() -> None:
    conversation = [
        *_pending_question_conversation(),
        ConversationMessage(
            role="user",
            content="PDF",
            metadata={
                "question_response": {"question_id": "terminal_output"},
            },
        ),
    ]

    prepared = prepare_user_question_metadata(
        conversation=conversation,
        message="One more thing",
        question_answer=None,
    )

    assert prepared.metadata is None


def test_free_text_without_a_pending_question_preserves_only_ui_language() -> None:
    prepared = prepare_user_question_metadata(
        conversation=[],
        message="Hello",
        question_answer=None,
        ui_language="en",
    )

    assert prepared.metadata == {"ui_language": "en"}


def test_blank_turn_does_not_claim_to_answer_a_pending_question() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_pending_question_conversation(),
        message="  \n",
        question_answer=None,
    )

    assert prepared.metadata is None


def _recommended_question(
    question_id: str = "terminal_output",
    *,
    recommended_option_id: str | None = "pdf_document",
) -> StructuredQuestionPayload:
    return StructuredQuestionPayload(
        question_id=question_id,
        question="Output?",
        options=[
            StructuredQuestionOptionPayload(
                id="pdf_document", label="PDF", value="pdf_document"
            ),
            StructuredQuestionOptionPayload(
                id="docx_document", label="Word", value="docx_document"
            ),
        ],
        selection_mode="single",
        allow_custom=False,
        recommended_option_id=recommended_option_id,
    )


def _asked(
    question: StructuredQuestionPayload,
    *,
    announced: StructuredQuestionPayload | None = None,
) -> list[ConversationMessage]:
    """The turn that presented a question, written the way the server writes it.

    `announced` exists only to build the inconsistent record a stale or
    tampered session could hold: the metadata names one question while the
    recorded payload describes another.
    """
    return [
        ConversationMessage(
            role="assistant",
            content="Which output?",
            metadata=metadata_for_assistant_question(announced or question),
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "ask_structured_question",
                    "arguments": question.model_dump(mode="json"),
                }
            ],
        )
    ]


def _recommended_question_conversation(
    question_id: str = "terminal_output",
    *,
    recommended_option_id: str | None = "pdf_document",
) -> list[ConversationMessage]:
    return _asked(
        _recommended_question(question_id, recommended_option_id=recommended_option_id)
    )


def test_delegated_answer_records_the_recommendation_as_the_users_answer() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_recommended_question_conversation(),
        message="",
        question_answer={
            "kind": "delegated_question_answer",
            "question_id": "terminal_output",
            "ui_language": "sv",
        },
    )

    assert prepared.metadata == {
        "question_answer": {
            "question_id": "terminal_output",
            "selected_option_id": "pdf_document",
            "selected_value": "pdf_document",
            "delegated": True,
        },
        "ui_language": "sv",
    }


def test_delegation_is_refused_when_the_question_recommends_nothing() -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_recommended_question_conversation(recommended_option_id=None),
            message="",
            question_answer={
                "kind": "delegated_question_answer",
                "question_id": "terminal_output",
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "delegation_without_recommendation"}


def test_delegation_is_refused_for_a_question_that_is_no_longer_pending() -> None:
    conversation = [
        *_recommended_question_conversation(),
        ConversationMessage(role="user", content="Word, please."),
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="",
            question_answer={
                "kind": "delegated_question_answer",
                "question_id": "terminal_output",
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "delegation_without_pending_question"}


def test_delegation_is_refused_when_it_names_another_question() -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_recommended_question_conversation(),
            message="",
            question_answer={
                "kind": "delegated_question_answer",
                "question_id": "post_processing_goal",
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "delegation_without_pending_question"}


def test_delegation_is_refused_when_the_recorded_recommendation_is_unusable() -> None:
    """A recommendation the record no longer offers cannot answer anything."""

    question = _recommended_question("terminal_output")
    conversation = _asked(question)
    arguments = question.model_dump(mode="json")
    arguments["recommended_option_id"] = "csv_document"
    conversation[0].tool_calls = [
        {"id": "tool-1", "name": "ask_structured_question", "arguments": arguments}
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="",
            question_answer={
                "kind": "delegated_question_answer",
                "question_id": "terminal_output",
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "delegation_without_pending_question"}


def test_a_client_cannot_claim_eneo_made_its_choice() -> None:
    """Delegation is the server's account of the answer, not the client's."""

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_recommended_question_conversation(),
            message="Word, please.",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "terminal_output",
                "selected_option_id": "docx_document",
                "delegated": True,
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "invalid_question_answer"}


def test_delegation_is_refused_when_the_recorded_question_disagrees_with_itself() -> (
    None
):
    """A record that names two different questions cannot settle either one."""

    conversation = _asked(
        _recommended_question("terminal_output"),
        announced=_recommended_question("post_processing_goal"),
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="",
            question_answer={
                "kind": "delegated_question_answer",
                "question_id": "post_processing_goal",
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "delegation_without_pending_question"}
