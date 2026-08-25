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
    DelegatedQuestionAnswerRequest,
    NamedContentFieldsEditRequest,
    StructuredQuestionAnswerMetadata,
    delegated_question_answer_from_input,
    metadata_for_user_message,
    named_content_fields_edit_from_input,
    question_answer_has_real_payload,
    question_answer_question_id,
    question_answer_values,
    question_response_to_metadata,
    requirements_confirmation_from_question_answer,
    structured_question_answer_request_from_input,
    ui_language_from_question_answer,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_field_identity import fold_result_field_name
from eneo.flows.ai_builder.ai_builder_question_state import (
    pending_user_requirement_question,
    pending_user_requirement_question_id,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from eneo.flows.ai_builder.planning_state import (
    NAMED_RESULT_FIELD_NAME_MAX_LENGTH,
    is_named_result_location_id,
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
    delegation = delegated_question_answer_from_input(question_answer)
    field_edit = named_content_fields_edit_from_input(question_answer)
    metadata: FlowPersistedJsonObject | None = None
    if requirements_confirmation is not None:
        metadata = metadata_for_user_message(question_answer=requirements_confirmation)
    elif field_edit is not None:
        metadata = metadata_for_user_message(
            question_answer=_validated_named_content_fields_edit(
                conversation=conversation,
                edit=field_edit,
            )
        )
    elif delegation is not None:
        metadata = metadata_for_user_message(
            question_answer=_validated_structured_question_answer(
                conversation=conversation,
                answer=_delegated_answer(
                    conversation=conversation,
                    delegation=delegation,
                ),
            )
        )
    elif question_answer is not None:
        metadata = metadata_for_user_message(
            question_answer=_validated_structured_question_answer(
                conversation=conversation,
                answer=_client_answer(question_answer),
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


def _client_answer(
    question_answer: AIBuilderQuestionAnswerInput,
) -> StructuredQuestionAnswerMetadata:
    """Read the selection the client stated, and only the selection."""
    request = structured_question_answer_request_from_input(question_answer)
    if request is None:
        _raise_invalid_question_payload("invalid_question_answer")
    return StructuredQuestionAnswerMetadata.model_validate(request.model_dump())


def _delegated_answer(
    *,
    conversation: list[ConversationMessage],
    delegation: DelegatedQuestionAnswerRequest,
) -> StructuredQuestionAnswerMetadata:
    """Answer the pending question with the recommendation it carried.

    The delegation names no option, so the answer is the one the user was
    shown as Eneo's own choice. Anything else — a closed question, a question
    with nothing to recommend — leaves the decision with the user.
    """
    pending = pending_user_requirement_question(conversation)
    if pending is None or (
        canonical_question_id(pending.question_id) != delegation.question_id
    ):
        _raise_invalid_question_payload("delegation_without_pending_question")

    if pending.recommended_option_id is None:
        _raise_invalid_question_payload("delegation_without_recommendation")

    recommended = next(
        option
        for option in pending.options
        if option.id == pending.recommended_option_id
    )
    return StructuredQuestionAnswerMetadata(
        question_id=delegation.question_id,
        selected_option_id=recommended.id,
        selected_value=recommended.value,
        delegated=True,
        ui_language=delegation.ui_language,
    )


def _validated_named_content_fields_edit(
    *,
    conversation: list[ConversationMessage],
    edit: NamedContentFieldsEditRequest,
) -> NamedContentFieldsEditRequest:
    """Normalize the submitted set, or refuse it in terms the card can act on.

    The two refusals are different user problems and stay separate: a stale
    version means the requirements moved under the user and the card has to be
    reloaded, while an unusable name means this one chip has to be renamed.

    A name is only refused for having no identity at all — blank, or nothing
    left after folding. Punctuation is not a server judgment: names reach the
    card exactly as the user wrote them, brackets and dots included, and the
    edit is mostly the card echoing them back.

    Which names the card did not already show is read here, against that same
    card, because this is the only point where the disclosure being answered is
    unambiguous. A later replay cannot re-derive it: the turns that shaped the
    card may have been compacted by then.
    """

    disclosure = resolve_requirements_state(conversation).latest_summary
    if (
        disclosure is None
        or edit.requirements_version != disclosure.requirements_version
    ):
        _raise_invalid_question_payload("requirements_version_stale")

    shown_by_id = {field.id: field for field in disclosure.named_content_fields}
    legacy_shown_by_fold = {
        fold_result_field_name(field.id): field
        for field in disclosure.named_content_fields
        if not is_named_result_location_id(field.id)
    }
    field_names: list[str] = []
    added_field_names: list[str] = []
    seen: set[tuple[str, str]] = set()
    for raw_value in edit.field_names:
        name = raw_value.strip()
        shown_field = shown_by_id.get(name)
        if shown_field is None and not is_named_result_location_id(name):
            shown_field = legacy_shown_by_fold.get(fold_result_field_name(name))
        if shown_field is not None:
            field_id = shown_field.id if is_named_result_location_id(name) else name
            seen_key = (
                ("id", field_id)
                if is_named_result_location_id(field_id)
                else ("name", fold_result_field_name(field_id))
            )
            if seen_key in seen:
                continue
            seen.add(seen_key)
            field_names.append(field_id)
            continue
        if is_named_result_location_id(name):
            raise AIBuilderBadRequestException(
                "Structured question answer could not be applied.",
                code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
                context={"reason": "unknown_field_id", "field_id": name},
            )
        folded = fold_result_field_name(name)
        if not name or not folded or len(name) > NAMED_RESULT_FIELD_NAME_MAX_LENGTH:
            raise AIBuilderBadRequestException(
                "Structured question answer could not be applied.",
                code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
                context={"reason": "invalid_field_name", "field_name": raw_value},
            )
        seen_key = ("name", folded)
        if seen_key in seen:
            # Two chips for one field is the same field said twice, not a
            # conflict the user has to resolve.
            continue
        seen.add(seen_key)
        field_names.append(name)
        added_field_names.append(name)
    # Deduplication keeps the FIRST spelling of a folded name; the request
    # validator normalized placement keys independently. Re-key the
    # placements to the spellings that actually survived, so replay's exact
    # lookup can never silently miss and drop a placed addition to root.
    # (Duplicate folded placement keys were already rejected upstream, so
    # each fold maps to at most one placement.)
    kept_by_fold = {fold_result_field_name(name): name for name in added_field_names}
    normalized_placements: dict[str, str] = {}
    for key, parent in edit.added_field_placements.items():
        kept = kept_by_fold.get(fold_result_field_name(key))
        if kept is not None:
            normalized_placements[kept] = parent
    return edit.model_copy(
        update={
            "field_names": field_names,
            "added_field_names": added_field_names,
            "added_field_placements": normalized_placements,
        }
    )


def _validated_structured_question_answer(
    *,
    conversation: list[ConversationMessage],
    answer: StructuredQuestionAnswerMetadata,
) -> StructuredQuestionAnswerMetadata:
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
