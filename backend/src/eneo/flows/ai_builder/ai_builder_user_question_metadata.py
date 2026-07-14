from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

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
    requirements_confirmation_from_question_answer,
    structured_question_answer_from_input,
    ui_language_from_question_answer,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    infer_question_answer_from_freeform,
    latest_pending_structured_question,
)
from eneo.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_pending_question_answer,
)
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    legal_slot_values,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )


@dataclass(frozen=True, slots=True)
class UserQuestionMetadataResolution:
    metadata: FlowPersistedJsonObject | None
    is_requirements_confirmation: bool
    used_auxiliary_llm: bool


@dataclass(frozen=True, slots=True)
class PreparedUserQuestionMetadata:
    metadata: FlowPersistedJsonObject | None
    is_requirements_confirmation: bool
    needs_auxiliary_llm: bool


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
            question_answer=_validated_structured_question_answer(question_answer)
        )

    needs_auxiliary_llm = False
    if metadata is None and not is_requirements_confirmation:
        inferred_answer = infer_question_answer_from_freeform(conversation, message)
        if inferred_answer is not None:
            metadata = metadata_for_user_message(question_answer=inferred_answer)
        else:
            needs_auxiliary_llm = (
                latest_pending_structured_question(conversation) is not None
            )

    if ui_language is not None:
        metadata = {
            **(metadata or {}),
            UI_LANGUAGE_METADATA_KEY: ui_language,
        }

    return PreparedUserQuestionMetadata(
        metadata=metadata,
        is_requirements_confirmation=is_requirements_confirmation,
        needs_auxiliary_llm=needs_auxiliary_llm,
    )


async def resolve_user_question_metadata(
    *,
    litellm_client: object,
    conversation: list[ConversationMessage],
    message: str,
    question_answer: AIBuilderQuestionAnswerInput | None,
    ui_language: str | None = None,
    completion_model_route: ResolvedCompletionModelRoute,
    prepared: PreparedUserQuestionMetadata | None = None,
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
) -> UserQuestionMetadataResolution:
    prepared = prepared or prepare_user_question_metadata(
        conversation=conversation,
        message=message,
        question_answer=question_answer,
        ui_language=ui_language,
    )
    metadata = prepared.metadata
    used_auxiliary_llm = False
    if prepared.needs_auxiliary_llm:
        adjudicated_answer = await adjudicate_pending_question_answer(
            litellm_client=litellm_client,
            completion_model_route=completion_model_route,
            conversation=conversation,
            user_message=message,
            before_provider_call=before_provider_call,
        )
        if adjudicated_answer is not None:
            metadata = {
                **(metadata or {}),
                **(
                    metadata_for_user_message(
                        question_answer=adjudicated_answer.to_question_answer()
                    )
                    or {}
                ),
            }
        used_auxiliary_llm = True

    return UserQuestionMetadataResolution(
        metadata=metadata,
        is_requirements_confirmation=prepared.is_requirements_confirmation,
        used_auxiliary_llm=used_auxiliary_llm,
    )


def _validated_structured_question_answer(
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

    return answer


def _has_unsupported_slot_value(
    answer: StructuredQuestionAnswerMetadata,
    question_id: str,
) -> bool:
    canonical_id = canonical_question_id(question_id)
    if canonical_id not in QUESTION_CATALOG:
        return False

    allowed_values = {value.casefold() for value in legal_slot_values(canonical_id)}
    return not question_answer_values(answer) <= allowed_values


def _raise_invalid_question_payload(reason: str) -> NoReturn:
    raise AIBuilderBadRequestException(
        "Structured question answer could not be applied.",
        code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
        context={"reason": reason},
    )
