from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_api_models import SendMessageRequest
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_for_assistant_question,
    requirements_summary_to_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_slot_classification_input,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AssumptionRowPayload,
    NamedContentFieldPayload,
    RequirementsSummaryPayload,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_question_state import last_answered_question
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    PreparedUserQuestionMetadata,
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import (
    ExactNamedResultPlacement,
    NamedResultEvidence,
    named_result_location_id,
)
from eneo.flows.ai_builder.question_catalog import render_summary_label


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
            conversation=_pending_question_conversation("flow_input_architecture"),
            message="Process each department separately",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "flow_input_architecture",
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
        # Dispatch numbers every question before persistence, so a fixture
        # standing in for a persisted question carries its number too.
        question_index=1,
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


def _disclosed_fields_conversation(
    version: str = "a" * 64,
    *,
    named_content_fields: list[NamedContentFieldPayload] | None = None,
) -> list[ConversationMessage]:
    """A session that has shown one disclosure naming two content fields."""

    summary = RequirementsSummaryPayload(
        summary="Rapporten ska bevara namngett innehåll: beslut, farhågor.",
        key_decisions=[],
        input_description="Ett mötesprotokoll.",
        output_description="En rapport.",
        requirements_version=version,
        named_content_fields=named_content_fields
        or [
            NamedContentFieldPayload(
                id="beslut",
                label="beslut",
                name="beslut",
                segments=[],
                unplaced=False,
                can_contain_fields=False,
            ),
            NamedContentFieldPayload(
                id="farhågor",
                label="farhågor",
                name="farhågor",
                segments=[],
                unplaced=False,
                can_contain_fields=False,
            ),
        ],
    )
    return [
        ConversationMessage(
            role="assistant",
            content="Granska sammanfattningen.",
            metadata=requirements_summary_to_metadata(summary),
        )
    ]


def _located_field(name: str, *segments: str) -> NamedContentFieldPayload:
    evidence = NamedResultEvidence(
        name=name,
        placement=ExactNamedResultPlacement(segments=segments),
        evidence=["quote:user_message:user-1:field"],
        confidence="high",
    )
    return NamedContentFieldPayload(
        id=named_result_location_id(evidence),
        label=name,
        name=name,
        segments=list(segments),
        unplaced=False,
        can_contain_fields=False,
    )


def _assumed_question_conversation(
    *,
    version: str = "a" * 64,
    question_id: str = "document_material_scope",
) -> list[ConversationMessage]:
    summary = RequirementsSummaryPayload(
        summary="The flow accepts documents.",
        key_decisions=[],
        input_description="Documents.",
        output_description="A report.",
        requirements_version=version,
        assumption_rows=[
            AssumptionRowPayload(
                question_id=question_id,
                slot_name=question_id,
                value="flexible_document_case",
                topic=render_summary_label(question_id, "en"),
                label="One or more documents",
            )
        ],
    )
    return [
        ConversationMessage(
            role="assistant",
            content="Review the requirements.",
            metadata=requirements_summary_to_metadata(summary),
        )
    ]


def test_current_assumption_can_be_persisted_as_a_reopen_command() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_assumed_question_conversation(),
        message="",
        question_answer={
            "kind": "reopen_question",
            "question_id": "document_material_scope",
            "requirements_version": "a" * 64,
        },
    )

    assert prepared.metadata == {
        "reopen_question": {
            "question_id": "document_material_scope",
            "requirements_version": "a" * 64,
        }
    }


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {
                "kind": "reopen_question",
                "question_id": "document_material_scope",
                "requirements_version": "b" * 64,
            },
            "requirements_version_stale",
        ),
        (
            {
                "kind": "reopen_question",
                "question_id": "terminal_output",
                "requirements_version": "a" * 64,
            },
            "question_not_assumed",
        ),
        (
            {
                "kind": "reopen_question",
                "question_id": "invented_question",
                "requirements_version": "a" * 64,
            },
            "question_unsupported",
        ),
    ],
)
def test_reopen_command_is_refused_against_the_current_disclosure(
    payload: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_assumed_question_conversation(),
            message="",
            question_answer=payload,
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": reason}


def test_editing_keeps_same_leaf_locations_distinct_by_opaque_id() -> None:
    events = _located_field("events")
    alerts = _located_field("alerts")
    events_timestamp = _located_field("timestamp", "events")
    alerts_timestamp = _located_field("timestamp", "alerts")
    kept_ids = [events.id, alerts.id, alerts_timestamp.id]

    prepared = prepare_user_question_metadata(
        conversation=_disclosed_fields_conversation(
            named_content_fields=[
                events,
                alerts,
                events_timestamp,
                alerts_timestamp,
            ]
        ),
        message="",
        question_answer={
            "kind": "named_content_fields_edit",
            "requirements_version": "a" * 64,
            "field_names": kept_ids,
        },
    )

    assert prepared.metadata is not None
    assert prepared.metadata["named_content_fields_edit"] == {
        "schema_version": 1,
        "requirements_version": "a" * 64,
        "field_names": kept_ids,
        "added_field_names": [],
        "added_field_placements": {},
    }


def test_editing_rejects_an_unknown_opaque_location_id_exactly() -> None:
    events = _located_field("events")
    unknown_id = _located_field("timestamp", "events").id

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_disclosed_fields_conversation(named_content_fields=[events]),
            message="",
            question_answer={
                "kind": "named_content_fields_edit",
                "requirements_version": "a" * 64,
                "field_names": [events.id, unknown_id],
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {
        "reason": "unknown_field_id",
        "field_id": unknown_id,
    }


def test_editing_the_field_list_records_the_set_the_user_left_standing() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_disclosed_fields_conversation(),
        message="",
        question_answer={
            "kind": "named_content_fields_edit",
            "requirements_version": "a" * 64,
            "field_names": ["beslut", "Beslutsdatum"],
            "ui_language": "sv",
        },
    )

    assert prepared.metadata == {
        "named_content_fields_edit": {
            "schema_version": 1,
            "requirements_version": "a" * 64,
            "field_names": ["beslut", "Beslutsdatum"],
            # The card showed "beslut" and "farhågor", so only the third name
            # is new. Keeping a chip and re-adding one look identical in the
            # resulting set, and only this card can tell them apart.
            "added_field_names": ["Beslutsdatum"],
            "added_field_placements": {},
        },
        "ui_language": "sv",
    }
    assert not prepared.is_requirements_confirmation


def test_editing_rekeys_placements_to_the_deduplicated_spelling() -> None:
    # Deduplication keeps the FIRST spelling ("Status"); the request
    # validator normalized the placement key independently. Admission must
    # re-key the placement to the surviving spelling so replay's exact
    # lookup cannot silently drop the placed addition to root.
    parent = _located_field("events")
    prepared = prepare_user_question_metadata(
        conversation=_disclosed_fields_conversation(named_content_fields=[parent]),
        message="",
        question_answer={
            "kind": "named_content_fields_edit",
            "requirements_version": "a" * 64,
            "field_names": [parent.id, "Status", "status"],
            "added_field_placements": {"Status": parent.id},
            "ui_language": "sv",
        },
    )

    edit = prepared.metadata["named_content_fields_edit"]
    assert edit["field_names"] == [parent.id, "Status"]
    assert edit["added_field_names"] == ["Status"]
    assert edit["added_field_placements"] == {"Status": parent.id}


def test_editing_the_field_list_is_refused_against_an_older_disclosure() -> None:
    # The user is answering a list they can see. If the requirements have moved
    # since, their set describes fields that are no longer the ones on offer.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_disclosed_fields_conversation(),
            message="",
            question_answer={
                "kind": "named_content_fields_edit",
                "requirements_version": "b" * 64,
                "field_names": ["beslut"],
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "requirements_version_stale"}


@pytest.mark.parametrize(
    "field_name",
    [
        pytest.param("   ", id="blank"),
        pytest.param("!!!", id="nothing-left-after-folding"),
    ],
)
def test_a_field_name_with_no_identity_is_refused_by_name(field_name: str) -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_disclosed_fields_conversation(),
            message="",
            question_answer={
                "kind": "named_content_fields_edit",
                "requirements_version": "a" * 64,
                "field_names": ["beslut", field_name],
            },
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {
        "reason": "invalid_field_name",
        "field_name": field_name,
    }


def test_a_field_name_keeps_the_punctuation_the_card_showed_it_with() -> None:
    # Names reach the card exactly as the user wrote them, and the edit is
    # mostly the card echoing them back. Reading one as a path or a shape
    # declaration would make an existing chip impossible to keep.
    prepared = prepare_user_question_metadata(
        conversation=_disclosed_fields_conversation(),
        message="",
        question_answer={
            "kind": "named_content_fields_edit",
            "requirements_version": "a" * 64,
            "field_names": ["attachment_inventory[]", "ärende.id"],
        },
    )

    assert prepared.metadata is not None
    assert prepared.metadata["named_content_fields_edit"] == {
        "schema_version": 1,
        "requirements_version": "a" * 64,
        "field_names": ["attachment_inventory[]", "ärende.id"],
        "added_field_names": ["attachment_inventory[]", "ärende.id"],
        "added_field_placements": {},
    }


def test_the_same_field_named_twice_is_recorded_once() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_disclosed_fields_conversation(),
        message="",
        question_answer={
            "kind": "named_content_fields_edit",
            "requirements_version": "a" * 64,
            "field_names": ["Beslut", " beslut ", "farhågor"],
        },
    )

    assert prepared.metadata is not None
    assert prepared.metadata["named_content_fields_edit"]["field_names"] == [
        "Beslut",
        "farhågor",
    ]


# ---- The displayed instance an explicit answer is bound to -----------------
#
# Every question and card shown carries the token minted when it was shown,
# stored in the payload the pending-question and requirements owners read
# back. An explicit answer names that token; one naming any other showing is
# refused as stale, nothing is applied, and the client reads the stored
# showing back. Questions and cards shown before the token existed keep the
# older rules.

_SHOWN_TOKEN = UUID("6f1c2a54-6f0e-4d8e-9d55-0e5f8f3b7a10")
_REPLACED_TOKEN = UUID("0a8e9b1c-51d2-4f7e-8a44-7c1b2d3e4f50")


def _with_token(
    question: StructuredQuestionPayload, token: UUID | None
) -> StructuredQuestionPayload:
    data = question.model_dump(mode="json")
    if token is not None:
        data["instance_token"] = str(token)
    return StructuredQuestionPayload.model_validate(data)


def _shown_question(token: UUID | None = _SHOWN_TOKEN) -> list[ConversationMessage]:
    return _asked(_with_token(_recommended_question(), token))


def _shown_card(token: UUID | None = _SHOWN_TOKEN) -> list[ConversationMessage]:
    summary = RequirementsSummaryPayload.model_validate(
        {
            "summary": "The flow accepts documents.",
            "key_decisions": [],
            "input_description": "Documents.",
            "output_description": "A report.",
            "requirements_version": "a" * 64,
            "assumption_rows": [
                {
                    "question_id": "document_material_scope",
                    "slot_name": "document_material_scope",
                    "value": "flexible_document_case",
                    "topic": render_summary_label("document_material_scope", "en"),
                    "label": "One or more documents",
                }
            ],
            "named_content_fields": [
                {
                    "id": "beslut",
                    "label": "beslut",
                    "name": "beslut",
                    "segments": [],
                    "unplaced": False,
                    "can_contain_fields": False,
                }
            ],
            **({"instance_token": str(token)} if token is not None else {}),
        }
    )
    return [
        ConversationMessage(
            role="assistant",
            content="Review the requirements.",
            metadata=requirements_summary_to_metadata(summary),
        )
    ]


def _token_field(token: UUID | None) -> dict[str, object]:
    return {"instance_token": str(token)} if token is not None else {}


def _structured_answer(token: UUID | None) -> dict[str, object]:
    return {
        "kind": "structured_question_answer",
        "question_id": "terminal_output",
        "selected_values": ["pdf_document"],
        **_token_field(token),
    }


def _custom_answer(token: UUID | None) -> dict[str, object]:
    return {
        "kind": "structured_question_answer",
        "question_id": "mapped_file_limit",
        "custom_value": "3",
        **_token_field(token),
    }


def _delegated(token: UUID | None) -> dict[str, object]:
    return {
        "kind": "delegated_question_answer",
        "question_id": "terminal_output",
        **_token_field(token),
    }


def _confirmation(token: UUID | None) -> dict[str, object]:
    return {
        "kind": "requirements_confirmation",
        "requirements_confirmed": True,
        "requirements_version": "a" * 64,
        **_token_field(token),
    }


def _card_edit(token: UUID | None) -> dict[str, object]:
    return {
        "kind": "named_content_fields_edit",
        "requirements_version": "a" * 64,
        "field_names": ["beslut", "Beslutsdatum"],
        **_token_field(token),
    }


def _reopen(token: UUID | None) -> dict[str, object]:
    return {
        "kind": "reopen_question",
        "question_id": "document_material_scope",
        "requirements_version": "a" * 64,
        **_token_field(token),
    }


def _shown_custom_question(
    token: UUID | None = _SHOWN_TOKEN,
) -> list[ConversationMessage]:
    question = StructuredQuestionPayload(
        question_id="mapped_file_limit",
        question="How many files may each run receive?",
        options=[StructuredQuestionOptionPayload(id="1", label="One", value="1")],
        selection_mode="single",
        allow_custom=True,
        question_index=1,
    )
    return _asked(_with_token(question, token))


_BRANCHES = [
    pytest.param(_shown_question, _structured_answer, "question", id="answer"),
    pytest.param(_shown_custom_question, _custom_answer, "question", id="custom"),
    pytest.param(_shown_question, _delegated, "question", id="delegated"),
    pytest.param(_shown_card, _confirmation, "requirements_summary", id="confirm"),
    pytest.param(_shown_card, _card_edit, "requirements_summary", id="card-edit"),
    pytest.param(_shown_card, _reopen, "requirements_summary", id="reopen"),
]


@pytest.mark.parametrize(("shown", "answer", "decision"), _BRANCHES)
def test_an_answer_to_a_replaced_showing_is_refused_as_stale(
    shown: Callable[..., list[ConversationMessage]],
    answer: Callable[[UUID | None], dict[str, object]],
    decision: str,
) -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=shown(),
            message="",
            question_answer=answer(_REPLACED_TOKEN),
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "stale_decision", "decision": decision}


@pytest.mark.parametrize(("shown", "answer", "decision"), _BRANCHES)
@pytest.mark.parametrize(
    ("ui_language", "reload_text"),
    [("sv", "Ladda om sidan"), ("en", "Reload the page"), (None, "Reload the page")],
)
def test_an_answer_naming_no_showing_is_told_to_reload_the_page(
    shown: Callable[..., list[ConversationMessage]],
    answer: Callable[[UUID | None], dict[str, object]],
    decision: str,
    ui_language: str | None,
    reload_text: str,
) -> None:
    # A page built before answers named their showing can never send a token.
    # Refusing it as stale would show the same question again for it to fail
    # on; it is told the one fix that works, in words it shows as they are.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=shown(),
            message="",
            question_answer=answer(None),
            ui_language=ui_language,
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": "client_outdated", "decision": decision}
    assert reload_text in str(exc_info.value)


@pytest.mark.parametrize(("shown", "answer", "decision"), _BRANCHES)
def test_an_answer_naming_the_stored_showing_is_applied(
    shown: Callable[..., list[ConversationMessage]],
    answer: Callable[[UUID | None], dict[str, object]],
    decision: str,
) -> None:
    prepared = prepare_user_question_metadata(
        conversation=shown(),
        message="",
        question_answer=answer(_SHOWN_TOKEN),
    )

    assert prepared.metadata is not None
    # The token binds the request; the recorded answer keeps today's shape,
    # which an older build must still be able to read back.
    assert str(_SHOWN_TOKEN) not in json.dumps(prepared.metadata)


@pytest.mark.parametrize(("shown", "answer", "decision"), _BRANCHES)
def test_an_answer_to_a_showing_from_before_tokens_keeps_the_older_rules(
    shown: Callable[..., list[ConversationMessage]],
    answer: Callable[[UUID | None], dict[str, object]],
    decision: str,
) -> None:
    tokenless = prepare_user_question_metadata(
        conversation=shown(None),
        message="",
        question_answer=answer(None),
    )
    tokened = prepare_user_question_metadata(
        conversation=shown(_SHOWN_TOKEN),
        message="",
        question_answer=answer(_SHOWN_TOKEN),
    )

    assert tokenless == tokened


@pytest.mark.parametrize(("shown", "answer", "decision"), _BRANCHES)
def test_a_token_sent_to_a_showing_from_before_tokens_is_refused(
    shown: Callable[..., list[ConversationMessage]],
    answer: Callable[[UUID | None], dict[str, object]],
    decision: str,
) -> None:
    # The showing on offer predates tokens, so a token names some other one.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=shown(None),
            message="",
            question_answer=answer(_SHOWN_TOKEN),
        )

    assert exc_info.value.context == {"reason": "stale_decision", "decision": decision}


def _shown_again(token: UUID) -> list[ConversationMessage]:
    """The same question put to the user a second time, as a new showing."""
    return _asked(_with_token(_recommended_question(), token))


def test_an_answer_to_the_showing_a_question_replaced_is_refused_as_stale() -> None:
    conversation = [
        *_shown_question(_REPLACED_TOKEN),
        ConversationMessage(role="user", content="Word, please."),
        *_shown_again(_SHOWN_TOKEN),
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="",
            question_answer=_structured_answer(_REPLACED_TOKEN),
        )

    assert exc_info.value.context == {
        "reason": "stale_decision",
        "decision": "question",
    }


def _answered_then_moved_on(
    later: list[ConversationMessage],
) -> list[ConversationMessage]:
    return [
        *_shown_question(),
        ConversationMessage(role="user", content="PDF"),
        *later,
    ]


@pytest.mark.parametrize(
    "later",
    [
        pytest.param(
            _asked(
                _with_token(
                    _recommended_question("post_processing_goal"), _REPLACED_TOKEN
                )
            ),
            id="another-question-open",
        ),
        pytest.param(_shown_card(_REPLACED_TOKEN), id="card-shown"),
        # A turn whose answer failed recorded it without answering it; retrying
        # or resending that answer re-answers the same showing.
        pytest.param([], id="answer-turn-failed"),
    ],
)
def test_an_earlier_question_is_re_answered_through_its_latest_showing(
    later: list[ConversationMessage],
) -> None:
    # Reopening an earlier answer from the card or the answered list shows the
    # question's latest showing again; its answer names that showing.
    conversation = _answered_then_moved_on(later)

    prepared = prepare_user_question_metadata(
        conversation=conversation,
        message="PDF",
        question_answer=_structured_answer(_SHOWN_TOKEN),
    )

    assert prepared.metadata is not None
    assert prepared.metadata["question_answer"] == {
        "question_id": "terminal_output",
        "selected_values": ["pdf_document"],
    }
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="PDF",
            question_answer=_structured_answer(uuid4()),
        )
    assert exc_info.value.context == {
        "reason": "stale_decision",
        "decision": "question",
    }


def test_the_token_binds_the_answer_to_the_question_it_was_shown_with() -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_shown_question(),
            message="",
            question_answer={
                "kind": "structured_question_answer",
                "question_id": "post_processing_goal",
                "selected_values": ["summarize_or_overview"],
                "instance_token": str(_SHOWN_TOKEN),
            },
        )

    assert exc_info.value.context == {
        "reason": "stale_decision",
        "decision": "question",
    }


def test_a_card_act_names_the_latest_showing_of_the_same_version() -> None:
    # Showing the same disclosure again is a new showing: the version is the
    # same, but an act on the earlier showing is still an act on a card the
    # user is no longer looking at.
    conversation = [*_shown_card(_REPLACED_TOKEN), *_shown_card(_SHOWN_TOKEN)]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="",
            question_answer=_confirmation(_REPLACED_TOKEN),
        )

    assert exc_info.value.context == {
        "reason": "stale_decision",
        "decision": "requirements_summary",
    }
    assert prepare_user_question_metadata(
        conversation=conversation,
        message="",
        question_answer=_confirmation(_SHOWN_TOKEN),
    ).is_requirements_confirmation


def test_a_bound_custom_answer_keeps_the_500_character_limit() -> None:
    at_limit = prepare_user_question_metadata(
        conversation=_shown_custom_question(),
        message="",
        question_answer={**_custom_answer(_SHOWN_TOKEN), "custom_value": "3" * 500},
    )
    assert at_limit.metadata is not None

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_shown_custom_question(),
            message="",
            question_answer={
                **_custom_answer(_SHOWN_TOKEN),
                "custom_value": "3" * 501,
            },
        )

    assert exc_info.value.context == {"reason": "invalid_question_answer"}


# ---- Typed text while a question is open -----------------------------------


def _reply(token: UUID, question_id: str = "terminal_output") -> dict[str, object]:
    return {
        "kind": "question_reply",
        "question_id": question_id,
        "instance_token": str(token),
    }


def test_text_bound_to_the_open_question_is_recorded_as_its_reply() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_shown_question(),
        message="Make it a PDF",
        question_answer=_reply(_SHOWN_TOKEN),
    )

    assert prepared.metadata == {
        "question_response": {"question_id": "terminal_output"}
    }
    assert prepared.answers_builder


def test_text_saying_nothing_about_itself_under_a_question_with_a_token_is_refused() -> (
    None
):
    # Another tab may have replaced the question this text was typed under,
    # and the text does not say whether it answers it or asks something new.
    # Only a page built before tokens sends that; it is told to reload.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_shown_question(),
            message="Make it a PDF",
            question_answer=None,
            ui_language="sv",
        )

    assert exc_info.value.context == {
        "reason": "client_outdated",
        "decision": "question",
    }
    assert "Ladda om sidan" in str(exc_info.value)


def test_text_declared_a_new_request_sets_the_open_question_aside() -> None:
    prepared = prepare_user_question_metadata(
        conversation=_shown_question(),
        message="Also summarise the attachments",
        question_answer={"kind": "new_request"},
    )

    assert prepared.metadata is None
    assert not prepared.answers_builder

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_shown_question(),
            message="  ",
            question_answer={"kind": "new_request"},
        )
    assert exc_info.value.context == {"reason": "empty_new_request"}


def test_text_with_no_question_open_needs_no_declaration() -> None:
    conversation = [
        *_shown_question(),
        ConversationMessage(
            role="user",
            content="PDF",
            metadata={"question_response": {"question_id": "terminal_output"}},
        ),
    ]

    prepared = prepare_user_question_metadata(
        conversation=conversation,
        message="And keep it short",
        question_answer=None,
    )

    assert prepared.metadata is None
    assert not prepared.answers_builder


def test_text_bound_to_a_replaced_question_is_refused_not_given_to_the_new_one() -> (
    None
):
    conversation = [
        *_shown_question(_REPLACED_TOKEN),
        ConversationMessage(role="user", content="PDF"),
        *_asked(
            _with_token(_recommended_question("post_processing_goal"), _SHOWN_TOKEN)
        ),
    ]

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="Actually, a Word document",
            question_answer=_reply(_REPLACED_TOKEN, "post_processing_goal"),
        )
    assert exc_info.value.context == {
        "reason": "stale_decision",
        "decision": "question",
    }

    with pytest.raises(AIBuilderBadRequestException) as bare_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="Actually, a Word document",
            question_answer=None,
        )
    assert bare_info.value.context == {
        "reason": "client_outdated",
        "decision": "question",
    }


def test_a_reply_carries_words() -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_shown_question(),
            message="  ",
            question_answer=_reply(_SHOWN_TOKEN),
        )

    assert exc_info.value.context == {"reason": "empty_question_reply"}


def test_bare_text_is_not_inferred_as_the_answer_to_a_question_with_a_token() -> None:
    bare = [*_shown_question(), ConversationMessage(role="user", content="PDF")]
    bound = [
        *_shown_question(),
        ConversationMessage(
            role="user",
            content="PDF",
            metadata={"question_response": {"question_id": "terminal_output"}},
        ),
    ]
    tokenless = [
        *_shown_question(None),
        ConversationMessage(role="user", content="PDF"),
    ]

    assert last_answered_question(bare) is None
    assert last_answered_question(bound) == ("terminal_output", "PDF")
    assert last_answered_question(tokenless) == ("terminal_output", "PDF")
    assert [
        source.question_id
        for source in build_slot_classification_input(bare, None).sources
        if source.kind == "user_message"
    ] == [None]
    assert [
        source.question_id
        for source in build_slot_classification_input(tokenless, None).sources
        if source.kind == "user_message"
    ] == ["terminal_output"]


def test_typed_words_never_re_answer_an_earlier_question() -> None:
    # Q1's showing is unchanged, but Q2 is the question on offer now: words
    # typed under Q1 were typed before Q2 replaced it.
    conversation = _answered_then_moved_on(
        _asked(
            _with_token(_recommended_question("post_processing_goal"), _REPLACED_TOKEN)
        )
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="A PDF after all",
            question_answer=_reply(_SHOWN_TOKEN),
        )

    assert exc_info.value.context == {
        "reason": "stale_decision",
        "decision": "question",
    }


def test_a_retried_turn_replies_to_the_question_its_own_message_answered() -> None:
    # The failed turn's message is already recorded, so the question reads as
    # answered; a retry under the same turn id is that same message again.
    failed = ConversationMessage(role="user", content="A PDF, one per case")
    conversation = [*_shown_question(), failed]

    prepared = prepare_user_question_metadata(
        conversation=conversation,
        message="A PDF, one per case",
        question_answer=_reply(_SHOWN_TOKEN),
        retried_turn_message_id=failed.message_id,
    )
    assert prepared.metadata == {
        "question_response": {"question_id": "terminal_output"}
    }

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=conversation,
            message="A PDF, one per case",
            question_answer=_reply(_SHOWN_TOKEN),
        )
    assert exc_info.value.context == {
        "reason": "stale_decision",
        "decision": "question",
    }


def test_re_answering_an_earlier_question_is_classified_against_that_question() -> None:
    # The client joins the labels of a multi-option answer into its text, which
    # no single value echoes, so the text is a source of its own: it belongs to
    # the question the answer names, not to the one open when it arrived.
    conversation = [
        *_answered_then_moved_on(
            _asked(
                _with_token(
                    _recommended_question("post_processing_goal"), _REPLACED_TOKEN
                )
            )
        ),
        ConversationMessage(
            role="user",
            content="PDF, Word",
            metadata={
                "question_answer": {
                    "question_id": "terminal_output",
                    "selected_option_ids": ["pdf_document", "docx_document"],
                    "selected_values": ["pdf_document", "docx_document"],
                }
            },
        ),
    ]

    assert last_answered_question(conversation) == ("terminal_output", "PDF, Word")
    assert [
        source.question_id
        for source in build_slot_classification_input(conversation, None).sources
        if source.kind == "user_message" and source.text == "PDF, Word"
    ] == ["terminal_output"]


def test_new_request_is_only_accepted_where_the_declaration_can_be_kept() -> None:
    # A question shown before tokens has no record that could keep a
    # declared new request apart from its answer, so none is accepted there.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=_shown_question(None),
            message="Also summarise the attachments",
            question_answer={"kind": "new_request"},
        )
    assert exc_info.value.context == {"reason": "new_request_under_untokened_question"}

    answered = [
        *_shown_question(None),
        ConversationMessage(role="user", content="PDF"),
    ]
    prepared = prepare_user_question_metadata(
        conversation=answered,
        message="Also summarise the attachments",
        question_answer={"kind": "new_request"},
    )
    assert prepared.metadata is None


def _file_only_request(question_answer: dict[str, object] | None) -> SendMessageRequest:
    return SendMessageRequest.model_validate(
        {
            "client_turn_id": str(uuid4()),
            "message": "",
            "file_ids": [str(uuid4())],
            **(
                {"question_answer": question_answer}
                if question_answer is not None
                else {}
            ),
        }
    )


def _admit(
    request: SendMessageRequest, conversation: list[ConversationMessage]
) -> object:
    return prepare_user_question_metadata(
        conversation=conversation,
        message=request.message,
        question_answer=request.question_answer,
        sends_files=bool(request.file_ids),
    )


def test_a_file_only_send_says_what_it_is_under_a_question_with_a_token() -> None:
    # Files close an open question just as words do; the public request allows
    # an empty message beside them, so the intent is decided the same way.
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        _admit(_file_only_request(None), _shown_question())
    assert exc_info.value.context == {
        "reason": "client_outdated",
        "decision": "question",
    }

    replied = _admit(_file_only_request(_reply(_SHOWN_TOKEN)), _shown_question())
    assert isinstance(replied, PreparedUserQuestionMetadata)
    assert replied.metadata == {"question_response": {"question_id": "terminal_output"}}

    declared = _admit(_file_only_request({"kind": "new_request"}), _shown_question())
    assert isinstance(declared, PreparedUserQuestionMetadata)
    assert declared.metadata is None
    assert not declared.answers_builder

    # A question from before tokens keeps what a file-only send did before.
    legacy = _admit(_file_only_request(None), _shown_question(None))
    assert isinstance(legacy, PreparedUserQuestionMetadata)
    assert legacy.metadata is None
