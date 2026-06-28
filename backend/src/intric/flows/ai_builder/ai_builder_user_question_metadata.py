from __future__ import annotations

from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    UI_LANGUAGE_METADATA_KEY,
    AIBuilderQuestionAnswerInput,
    metadata_for_user_message,
    requirements_confirmation_from_question_answer,
    ui_language_from_question_answer,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_framework_policy import (
    infer_question_answer_from_freeform,
    latest_pending_structured_question,
)
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_pending_question_answer,
)
from intric.flows.domain.flow import FlowPersistedJsonObject


@dataclass(frozen=True, slots=True)
class UserQuestionMetadataResolution:
    metadata: FlowPersistedJsonObject | None
    is_requirements_confirmation: bool
    used_auxiliary_llm: bool


async def resolve_user_question_metadata(
    *,
    litellm_client: object,
    conversation: list[ConversationMessage],
    message: str,
    question_answer: AIBuilderQuestionAnswerInput | None,
    ui_language: str | None = None,
    litellm_model: str,
    litellm_kwargs: dict[str, object],
) -> UserQuestionMetadataResolution:
    if ui_language is None and question_answer is not None:
        ui_language = ui_language_from_question_answer(question_answer)

    is_requirements_confirmation = (
        requirements_confirmation_from_question_answer(question_answer) is not None
    )
    metadata: FlowPersistedJsonObject | None = None
    if question_answer is not None:
        metadata = metadata_for_user_message(question_answer=question_answer)

    used_auxiliary_llm = False
    if metadata is None and not is_requirements_confirmation:
        inferred_answer = infer_question_answer_from_freeform(conversation, message)
        if inferred_answer is not None:
            metadata = metadata_for_user_message(question_answer=inferred_answer)
        elif latest_pending_structured_question(conversation) is not None:
            adjudicated_answer = await adjudicate_pending_question_answer(
                litellm_client=litellm_client,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                conversation=conversation,
                user_message=message,
            )
            if adjudicated_answer is not None:
                metadata = metadata_for_user_message(
                    question_answer=adjudicated_answer.to_question_answer()
                )
            used_auxiliary_llm = True

    if ui_language is not None:
        metadata = {
            **(metadata or {}),
            UI_LANGUAGE_METADATA_KEY: ui_language,
        }

    return UserQuestionMetadataResolution(
        metadata=metadata,
        is_requirements_confirmation=is_requirements_confirmation,
        used_auxiliary_llm=used_auxiliary_llm,
    )
