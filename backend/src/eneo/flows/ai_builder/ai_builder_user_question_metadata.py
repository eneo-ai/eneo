from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NoReturn
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_canonicalization import (
    canonical_question_id,
    is_supported_structured_question_id,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    UI_LANGUAGE_METADATA_KEY,
    AIBuilderQuestionAnswerInput,
    DelegatedQuestionAnswerRequest,
    NamedContentFieldsEditRequest,
    ReopenQuestionRequest,
    StructuredQuestionAnswerMetadata,
    delegated_question_answer_from_input,
    metadata_for_user_message,
    named_content_fields_edit_from_input,
    new_request_from_input,
    question_answer_has_real_payload,
    question_answer_question_id,
    question_answer_values,
    question_reply_from_input,
    question_response_to_metadata,
    reopen_question_from_input,
    requirements_confirmation_from_question_answer,
    structured_question_answer_request_from_input,
    ui_language_from_question_answer,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import StructuredQuestionPayload
from eneo.flows.ai_builder.ai_builder_field_identity import fold_result_field_name
from eneo.flows.ai_builder.ai_builder_question_state import (
    latest_shown_question,
    pending_user_requirement_question,
    pending_user_requirement_question_id,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import resolve_locale
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from eneo.flows.ai_builder.planning_state import (
    NAMED_RESULT_FIELD_NAME_MAX_LENGTH,
    is_named_result_location_id,
)
from eneo.flows.ai_builder.question_catalog import (
    QUESTION_CATALOG,
    Locale,
    legal_slot_values,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject


@dataclass(frozen=True, slots=True)
class PreparedUserQuestionMetadata:
    metadata: FlowPersistedJsonObject | None
    is_requirements_confirmation: bool
    # The turn answers something the Builder asked - a structured answer, a
    # requirements confirmation, or free text sent while a question waits -
    # rather than opening a request of its own.
    answers_builder: bool = False


def prepare_user_question_metadata(
    *,
    conversation: list[ConversationMessage],
    message: str,
    question_answer: AIBuilderQuestionAnswerInput | None,
    ui_language: str | None = None,
    retried_turn_message_id: str | None = None,
    sends_files: bool = False,
) -> PreparedUserQuestionMetadata:
    """Read what the user answered, refusing answers to a replaced showing.

    `retried_turn_message_id` names the user message of the turn this request
    retries under the same client turn id, when that turn never committed. The
    message is already in the conversation, but it is this request's own and
    has not answered anything yet.

    `sends_files` says the turn attaches files. Files close an open question
    just as words do, so a file-only turn says what it is exactly as text
    must.
    """
    if ui_language is None and question_answer is not None:
        ui_language = ui_language_from_question_answer(question_answer)

    requirements_confirmation = requirements_confirmation_from_question_answer(
        question_answer
    )
    is_requirements_confirmation = requirements_confirmation is not None
    delegation = delegated_question_answer_from_input(question_answer)
    reopen = reopen_question_from_input(question_answer)
    field_edit = named_content_fields_edit_from_input(question_answer)
    reply = question_reply_from_input(question_answer)
    new_request = new_request_from_input(question_answer)
    metadata: FlowPersistedJsonObject | None = None
    if new_request is not None:
        # Declared, not inferred: the turn sets the open question aside. A
        # question shown before tokens has no reader that could tell the
        # declaration from an answer, so it is only accepted where it can be
        # kept: with no question open, or one that carries a token.
        if not (message.strip() or sends_files):
            _raise_invalid_question_payload("empty_new_request")
        if pending_user_requirement_question_id(conversation) is not None:
            pending = pending_user_requirement_question(conversation)
            if pending is None or pending.instance_token is None:
                _raise_invalid_question_payload("new_request_under_untokened_question")
    elif reply is not None:
        if not (message.strip() or sends_files):
            _raise_invalid_question_payload("empty_question_reply")
        if not is_supported_structured_question_id(reply.question_id):
            _raise_invalid_question_payload("unsupported_question_id")
        _require_open_question(
            conversation=[
                message
                for message in conversation
                if message.message_id != retried_turn_message_id
            ],
            question_id=reply.question_id,
            instance_token=reply.instance_token,
        )
        metadata = question_response_to_metadata(reply.question_id)
    elif requirements_confirmation is not None:
        _require_displayed_summary(
            conversation=conversation,
            ui_language=ui_language,
            instance_token=requirements_confirmation.instance_token,
        )
        metadata = metadata_for_user_message(question_answer=requirements_confirmation)
    elif reopen is not None:
        _require_displayed_summary(
            conversation=conversation,
            ui_language=ui_language,
            instance_token=reopen.instance_token,
        )
        metadata = metadata_for_user_message(
            question_answer=_validated_reopen_question(
                conversation=conversation,
                reopen=reopen,
            )
        )
    elif field_edit is not None:
        _require_displayed_summary(
            conversation=conversation,
            ui_language=ui_language,
            instance_token=field_edit.instance_token,
        )
        metadata = metadata_for_user_message(
            question_answer=_validated_named_content_fields_edit(
                conversation=conversation,
                edit=field_edit,
            )
        )
    elif delegation is not None:
        _require_displayed_question(
            conversation=conversation,
            ui_language=ui_language,
            question_id=delegation.question_id,
            instance_token=delegation.instance_token,
        )
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
        answer = _client_answer(question_answer)
        _require_displayed_question(
            conversation=conversation,
            ui_language=ui_language,
            question_id=answer.question_id,
            instance_token=answer.instance_token,
        )
        metadata = metadata_for_user_message(
            question_answer=_validated_structured_question_answer(
                conversation=conversation,
                answer=answer,
            )
        )

    answers_builder = question_answer is not None and new_request is None
    if question_answer is None and (message.strip() or sends_files):
        # Text that says nothing about itself is only read as a reply to a
        # question shown before tokens existed. Once the open question
        # carries a token, text says what it is - a `question_reply` naming
        # that showing, or a `new_request` - and text that says neither comes
        # from a page built before, which is told to reload rather than have
        # its intent guessed.
        pending_question_id = pending_user_requirement_question_id(conversation)
        if pending_question_id is not None:
            pending = pending_user_requirement_question(conversation)
            _require_named_showing(
                stored_token=pending.instance_token if pending is not None else None,
                instance_token=None,
                decision="question",
                ui_language=ui_language,
            )
            if message.strip():
                metadata = question_response_to_metadata(pending_question_id)
                answers_builder = True

    if ui_language is not None:
        metadata = {
            **(metadata or {}),
            UI_LANGUAGE_METADATA_KEY: ui_language,
        }

    return PreparedUserQuestionMetadata(
        metadata=metadata,
        is_requirements_confirmation=is_requirements_confirmation,
        answers_builder=answers_builder,
    )


def _require_displayed_question(
    *,
    conversation: list[ConversationMessage],
    ui_language: str | None,
    question_id: str | None,
    instance_token: UUID | None,
) -> None:
    """Refuse an answer that names a showing its question no longer has.

    An answer to the open question names the showing the pending-question
    owner reads back. An answer to another question re-answers one asked
    earlier, which the user reopens from the card or from their earlier
    answers, and names that question's latest showing; the same question shown
    again since replaces the earlier showing. The token compared is always the
    one stored with the showing, never one derived again.

    A showing from before tokens existed carries none; an answer to it that
    names none either is left to the rules that applied before, and an answer
    naming a token there answers some other showing.
    """

    open_question = pending_user_requirement_question(conversation)
    shown: StructuredQuestionPayload | None = None
    if open_question is not None and (
        question_id is None
        or canonical_question_id(question_id)
        == canonical_question_id(open_question.question_id)
    ):
        shown = open_question
    elif question_id is not None:
        shown = latest_shown_question(conversation, question_id=question_id)
    _require_named_showing(
        stored_token=shown.instance_token if shown is not None else None,
        instance_token=instance_token,
        decision="question",
        ui_language=ui_language,
    )


def _require_open_question(
    *,
    conversation: list[ConversationMessage],
    question_id: str,
    instance_token: UUID,
) -> None:
    """Refuse typed words that name a showing other than the open question's.

    Unlike a structured answer, typed words never re-answer an earlier
    question: they were typed under the question that was open, so they reply
    to it only while it is still the one on offer, same question and same
    showing.
    """

    shown = pending_user_requirement_question(conversation)
    if (
        shown is None
        or shown.instance_token != instance_token
        or canonical_question_id(shown.question_id)
        != canonical_question_id(question_id)
    ):
        _raise_stale_decision("question")


def _require_displayed_summary(
    *,
    conversation: list[ConversationMessage],
    ui_language: str | None,
    instance_token: UUID | None,
) -> None:
    """Refuse a card act that names a showing other than the latest card.

    The latest card is the one the requirements owner reads back, with the
    token stored on it. A card shown before tokens existed carries none, and an
    act naming none either keeps the version checks that applied before.
    """

    shown = resolve_requirements_state(conversation).latest_summary
    _require_named_showing(
        stored_token=shown.instance_token if shown is not None else None,
        instance_token=instance_token,
        decision="requirements_summary",
        ui_language=ui_language,
    )


_ShowingKind = Literal["question", "requirements_summary"]

# Said by the server because a page built before answers named their showing
# cannot know the reason: it shows this message as it is, so the message has
# to carry the one fix that works.
_CLIENT_OUTDATED_MESSAGES: dict[Locale, str] = {
    "sv": "Sidan är inaktuell. Ladda om sidan och svara igen.",
    "en": "This page is out of date. Reload the page and answer again.",
}


def _require_named_showing(
    *,
    stored_token: UUID | None,
    instance_token: UUID | None,
    decision: _ShowingKind,
    ui_language: str | None,
) -> None:
    if stored_token is None and instance_token is None:
        return
    if instance_token is None:
        # The showing carries a token and the answer names none: a page from
        # before tokens existed, which will never send one. Refusing it as
        # stale would only show the same question again for it to fail on.
        raise AIBuilderBadRequestException(
            _CLIENT_OUTDATED_MESSAGES[resolve_locale(ui_language)],
            code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
            context={"reason": "client_outdated", "decision": decision},
        )
    if instance_token != stored_token:
        _raise_stale_decision(decision)


def _raise_stale_decision(decision: _ShowingKind) -> NoReturn:
    # Nothing is applied. The client reads the session back and shows the
    # stored question or card again, the one this answer should have named.
    raise AIBuilderBadRequestException(
        "The question or summary was answered after it was replaced.",
        code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
        context={"reason": "stale_decision", "decision": decision},
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


def _validated_reopen_question(
    *,
    conversation: list[ConversationMessage],
    reopen: ReopenQuestionRequest,
) -> ReopenQuestionRequest:
    disclosure = resolve_requirements_state(conversation).latest_summary
    if (
        disclosure is None
        or reopen.requirements_version != disclosure.requirements_version
    ):
        _raise_invalid_question_payload("requirements_version_stale")
    if reopen.question_id not in QUESTION_CATALOG:
        _raise_invalid_question_payload("question_unsupported")
    if reopen.question_id not in {
        row.question_id for row in disclosure.assumption_rows
    }:
        _raise_invalid_question_payload("question_not_assumed")
    return reopen


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
