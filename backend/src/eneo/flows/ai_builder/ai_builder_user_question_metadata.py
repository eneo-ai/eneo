from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from eneo.flows.ai_builder.ai_builder_canonicalization import (
    canonical_question_id,
    is_supported_structured_question_id,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    UI_LANGUAGE_METADATA_KEY,
    AIBuilderQuestionAnswerInput,
    StructuredQuestionAnswerMetadata,
    metadata_for_user_message,
    question_answer_has_real_payload,
    question_answer_question_id,
    question_answer_values,
    question_response_to_metadata,
    requirements_confirmation_from_question_answer,
    structured_question_answer_from_input,
    ui_language_from_question_answer,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_question_state import (
    pending_user_requirement_question_id,
)
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    legal_slot_values,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject


@dataclass(frozen=True, slots=True)
class PreparedUserQuestionMetadata:
    metadata: FlowPersistedJsonObject | None
    is_requirements_confirmation: bool


def prepare_user_question_metadata(
    *,
    conversation: list[ConversationMessage],
    message: str,
    question_answer: AIBuilderQuestionAnswerInput | None,
    ui_language: str | None = None,
) -> PreparedUserQuestionMetadata:
    if ui_language is None and question_answer is not None:
        ui_language = ui_language_from_question_answer(question_answer)

    requirements_confirmation = requirements_confirmation_from_question_answer(
        question_answer
    )
    is_requirements_confirmation = requirements_confirmation is not None
    metadata: FlowPersistedJsonObject | None = None
    if requirements_confirmation is not None:
        metadata = metadata_for_user_message(question_answer=requirements_confirmation)
    elif question_answer is not None:
        metadata = metadata_for_user_message(
            question_answer=_validated_structured_question_answer(
                conversation=conversation,
                question_answer=question_answer,
            )
        )

    if metadata is None and not is_requirements_confirmation and message.strip():
        pending_question_id = pending_user_requirement_question_id(conversation)
        if pending_question_id is not None:
            metadata = question_response_to_metadata(pending_question_id)

    if ui_language is not None:
        metadata = {
            **(metadata or {}),
            UI_LANGUAGE_METADATA_KEY: ui_language,
        }

    return PreparedUserQuestionMetadata(
        metadata=metadata,
        is_requirements_confirmation=is_requirements_confirmation,
    )


def _validated_structured_question_answer(
    *,
    conversation: list[ConversationMessage],
    question_answer: AIBuilderQuestionAnswerInput,
) -> StructuredQuestionAnswerMetadata:
    answer = structured_question_answer_from_input(question_answer)
    if answer is None:
        _raise_invalid_question_payload("invalid_question_answer")

    question_id = question_answer_question_id(answer)
    if question_id is None:
        _raise_invalid_question_payload("missing_question_id")

    if not is_supported_structured_question_id(question_id):
        _raise_invalid_question_payload("unsupported_question_id")

    if not question_answer_has_real_payload(answer):
        _raise_invalid_question_payload("empty_question_answer")

    if _has_unsupported_slot_value(answer, question_id):
        _raise_invalid_question_payload("unsupported_question_value")

    if canonical_question_id(question_id) == "schema_direction":
        from eneo.flows.ai_builder.ai_builder_schema_evidence import (
            is_valid_structured_schema_direction_answer,
        )

        if not is_valid_structured_schema_direction_answer(
            conversation=conversation,
            answer=answer,
        ):
            _raise_invalid_question_payload("invalid_schema_direction")

    return answer


def _has_unsupported_slot_value(
    answer: StructuredQuestionAnswerMetadata,
    question_id: str,
) -> bool:
    canonical_id = canonical_question_id(question_id)
    if canonical_id not in QUESTION_CATALOG:
        return answer.custom_value is not None

    template = QUESTION_CATALOG[canonical_id]
    answer_values = question_answer_values(answer)
    if answer.custom_value is not None:
        if not template.allow_custom:
            return True
        answer_values.discard(answer.custom_value.strip().casefold())

    allowed_values = {value.casefold() for value in legal_slot_values(canonical_id)}
    return not answer_values <= allowed_values


def _raise_invalid_question_payload(reason: str) -> NoReturn:
    raise AIBuilderBadRequestException(
        "Structured question answer could not be applied.",
        code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
        context={"reason": reason},
    )
