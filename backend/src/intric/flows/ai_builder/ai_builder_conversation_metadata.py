"""Typed owners for AI Builder conversation metadata JSON shapes.

Request-only discriminators such as question_answer.kind are removed before
persistence. Persisted conversation metadata keeps the historical compact keys
but all production readers/writers should go through this module so the JSONB
contract has one owner.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from intric.flows.ai_builder.ai_builder_canonicalization import (
    normalize_question_answer,
    normalize_structured_question_payload,
)
from intric.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from intric.flows.flow_authoring_spec import JsonObject

QUESTION_ANSWER_METADATA_KEY = "question_answer"
REQUIREMENTS_CONFIRMED_METADATA_KEY = "requirements_confirmed"
REQUIREMENTS_SUMMARY_METADATA_KEY = "requirements_summary"
REQUIREMENTS_VERSION_METADATA_KEY = "requirements_version"
UI_LANGUAGE_METADATA_KEY = "ui_language"
FILE_IDS_METADATA_KEY = "file_ids"
EDIT_CONTEXT_METADATA_KEY = "edit_context"
ASSISTANT_QUESTION_ID_METADATA_KEY = "question_id"

JsonScalar: TypeAlias = str | int | float | bool | None


class StructuredQuestionAnswerMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["structured_question_answer"] = "structured_question_answer"
    question_id: str | None = None
    selected_option_ids: list[str] | None = None
    selected_values: list[JsonScalar] | None = None
    selected_option_id: str | None = None
    selected_value: JsonScalar = None
    answer: JsonScalar = None
    custom_value: str | None = None
    ui_language: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_ids(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        payload = dict(cast(Mapping[str, Any], data))
        payload.setdefault("kind", "structured_question_answer")
        return normalize_question_answer(payload)


class RequirementsConfirmationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["requirements_confirmation"] = "requirements_confirmation"
    requirements_confirmed: Literal[True] = True
    requirements_version: str | None = None
    ui_language: str | None = None


AIBuilderQuestionAnswerRequest: TypeAlias = Annotated[
    StructuredQuestionAnswerMetadata | RequirementsConfirmationMetadata,
    Field(discriminator="kind"),
]

AIBuilderQuestionAnswerInput: TypeAlias = (
    StructuredQuestionAnswerMetadata
    | RequirementsConfirmationMetadata
    | Mapping[str, Any]
)


class RequirementsSummaryMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements_summary: RequirementsSummaryPayload
    requirements_version: str | None = None


class PersistedAssistantToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    arguments: JsonObject = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def parse_json_arguments(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        payload = dict(cast(Mapping[str, Any], data))
        raw_arguments = payload.get("arguments")
        if isinstance(raw_arguments, str):
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                payload["arguments"] = parsed
        return payload


class RuntimeToolFunction(Protocol):
    name: str


class RuntimeToolCall(Protocol):
    id: str
    function: RuntimeToolFunction


def _metadata_mapping(metadata: object) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], metadata) if isinstance(metadata, Mapping) else None


def _mapping_value(value: object) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def _model_or_mapping_data(value: AIBuilderQuestionAnswerInput) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return dict(value)


def _question_answer_payload(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> JsonObject:
    if isinstance(answer, StructuredQuestionAnswerMetadata):
        return answer.model_dump(mode="json", exclude_none=True)
    return normalize_question_answer(answer)


def _object_sequence(value: object) -> Sequence[object] | None:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return None
    return cast(Sequence[object], value)


def requirements_confirmation_from_question_answer(
    value: AIBuilderQuestionAnswerInput | None,
) -> RequirementsConfirmationMetadata | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    if data.get("kind") not in (None, "requirements_confirmation"):
        return None
    if data.get("requirements_confirmed") is not True:
        return None
    data.setdefault("kind", "requirements_confirmation")
    try:
        return RequirementsConfirmationMetadata.model_validate(data)
    except ValidationError:
        return None


def structured_question_answer_from_input(
    value: AIBuilderQuestionAnswerInput | None,
) -> StructuredQuestionAnswerMetadata | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    if data.get("kind") not in (None, "structured_question_answer"):
        return None
    if data.get("requirements_confirmed") is True:
        return None
    data.setdefault("kind", "structured_question_answer")
    try:
        return StructuredQuestionAnswerMetadata.model_validate(data)
    except ValidationError:
        return None


def question_answer_from_metadata(
    metadata: object,
) -> StructuredQuestionAnswerMetadata | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    answer = _mapping_value(metadata_map.get(QUESTION_ANSWER_METADATA_KEY))
    if answer is None:
        return None
    return structured_question_answer_from_input(answer)


def question_answer_to_metadata(
    value: AIBuilderQuestionAnswerInput,
) -> JsonObject:
    answer = structured_question_answer_from_input(value)
    if answer is None:
        return {}
    payload = answer.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"kind", "ui_language"},
    )
    return {QUESTION_ANSWER_METADATA_KEY: payload}


def requirements_confirmation_to_metadata(
    value: AIBuilderQuestionAnswerInput,
) -> JsonObject:
    confirmation = requirements_confirmation_from_question_answer(value)
    if confirmation is None:
        return {}
    return confirmation.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"kind", "ui_language"},
    )


def requirements_confirmation_from_metadata(
    metadata: object,
) -> RequirementsConfirmationMetadata | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    if metadata_map.get(REQUIREMENTS_CONFIRMED_METADATA_KEY) is not True:
        return None
    try:
        return RequirementsConfirmationMetadata.model_validate(
            {
                "kind": "requirements_confirmation",
                "requirements_confirmed": True,
                "requirements_version": metadata_map.get(
                    REQUIREMENTS_VERSION_METADATA_KEY
                ),
            }
        )
    except ValidationError:
        return None


def requirements_summary_to_metadata(
    payload: RequirementsSummaryPayload | Mapping[str, Any],
) -> JsonObject:
    summary = (
        payload
        if isinstance(payload, RequirementsSummaryPayload)
        else RequirementsSummaryPayload.model_validate(payload)
    )
    version = summary.requirements_version
    if not isinstance(version, str) or not version:
        raise ValueError("requirements_summary metadata requires requirements_version")
    return {
        REQUIREMENTS_SUMMARY_METADATA_KEY: summary.model_dump(
            mode="json", exclude_none=True
        ),
        REQUIREMENTS_VERSION_METADATA_KEY: version,
    }


def requirements_summary_from_metadata(
    metadata: object,
) -> RequirementsSummaryMetadata | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    summary = _mapping_value(metadata_map.get(REQUIREMENTS_SUMMARY_METADATA_KEY))
    version = metadata_map.get(REQUIREMENTS_VERSION_METADATA_KEY)
    if summary is None:
        return None
    try:
        summary_payload = RequirementsSummaryPayload.model_validate(summary)
        return RequirementsSummaryMetadata.model_validate(
            {
                "requirements_summary": summary_payload,
                "requirements_version": (
                    version
                    if isinstance(version, str)
                    else summary_payload.requirements_version
                ),
            }
        )
    except ValidationError:
        return None


def metadata_has_requirements_summary(metadata: object) -> bool:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return False
    return (
        _mapping_value(metadata_map.get(REQUIREMENTS_SUMMARY_METADATA_KEY)) is not None
    )


def requirements_version_from_metadata(metadata: object) -> str | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    version = metadata_map.get(REQUIREMENTS_VERSION_METADATA_KEY)
    return version if isinstance(version, str) and version else None


def metadata_has_question_answer(metadata: object) -> bool:
    return question_answer_from_metadata(metadata) is not None


def metadata_has_real_question_answer(metadata: object) -> bool:
    answer = question_answer_from_metadata(metadata)
    return answer is not None and question_answer_has_real_payload(answer)


def question_answer_has_real_payload(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> bool:
    payload = _question_answer_payload(answer)
    question_id = payload.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        return False
    for key in (
        "selected_option_id",
        "selected_value",
        "answer",
        "custom_value",
    ):
        raw_value = payload.get(key)
        if _text_from_scalar(raw_value):
            return True
    for key in ("selected_option_ids", "selected_values"):
        raw_values = _object_sequence(payload.get(key))
        if raw_values is None:
            continue
        if any(_text_from_scalar(value) for value in raw_values):
            return True
    return False


def question_answer_text_candidates(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> set[str]:
    payload = _question_answer_payload(answer)
    candidates: set[str] = set()
    for key in (
        "selected_option_id",
        "selected_value",
        "answer",
        "custom_value",
    ):
        raw_value = payload.get(key)
        text = _text_from_scalar(raw_value)
        if text is not None:
            candidates.add(text.casefold())
    for key in ("selected_option_ids", "selected_values"):
        raw_values = _object_sequence(payload.get(key))
        if raw_values is None:
            continue
        for raw_value in raw_values:
            text = _text_from_scalar(raw_value)
            if text is not None:
                candidates.add(text.casefold())
    return candidates


def question_answer_values(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> set[str]:
    payload = _question_answer_payload(answer)
    values: set[str] = set()
    for raw_values in (
        payload.get("selected_option_ids"),
        payload.get("selected_values"),
    ):
        value_sequence = _object_sequence(raw_values)
        if value_sequence is None:
            continue
        for value in value_sequence:
            text = _text_from_scalar(value)
            if text is not None:
                values.add(text.casefold())
    for raw_key in ("selected_option_id", "selected_value", "answer", "custom_value"):
        raw_value = payload.get(raw_key)
        text = _text_from_scalar(raw_value)
        if text is not None:
            values.add(text.casefold())
    return values


def question_answer_question_id(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> str | None:
    payload = _question_answer_payload(answer)
    question_id = payload.get("question_id")
    return question_id if isinstance(question_id, str) and question_id else None


def ui_language_from_metadata(metadata: object) -> Literal["sv", "en"] | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    value = metadata_map.get(UI_LANGUAGE_METADATA_KEY)
    return value if value in {"sv", "en"} else None


def ui_language_from_question_answer(
    value: AIBuilderQuestionAnswerInput | None,
) -> Literal["sv", "en"] | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    raw = data.get(UI_LANGUAGE_METADATA_KEY)
    return raw if raw in {"sv", "en"} else None


def assistant_question_id_from_metadata(metadata: object) -> str | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    question_id = metadata_map.get(ASSISTANT_QUESTION_ID_METADATA_KEY)
    return question_id if isinstance(question_id, str) and question_id else None


def file_ids_from_metadata(metadata: object) -> list[UUID]:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return []
    raw_file_ids = metadata_map.get(FILE_IDS_METADATA_KEY)
    file_id_values = _object_sequence(raw_file_ids)
    if file_id_values is None:
        return []
    file_ids: list[UUID] = []
    for raw_file_id in file_id_values:
        try:
            file_ids.append(
                raw_file_id if isinstance(raw_file_id, UUID) else UUID(str(raw_file_id))
            )
        except (TypeError, ValueError):
            continue
    return file_ids


def metadata_for_user_message(
    *,
    question_answer: AIBuilderQuestionAnswerInput | None = None,
    ui_language: str | None = None,
    file_ids: Sequence[UUID] | None = None,
    edit_context: AIBuilderPlanEditContext | None = None,
) -> JsonObject | None:
    metadata: JsonObject = {}
    if question_answer is not None:
        confirmation_metadata = requirements_confirmation_to_metadata(question_answer)
        metadata.update(
            confirmation_metadata or question_answer_to_metadata(question_answer)
        )
    if ui_language is not None:
        metadata[UI_LANGUAGE_METADATA_KEY] = ui_language
    if file_ids:
        metadata[FILE_IDS_METADATA_KEY] = [str(file_id) for file_id in file_ids]
    if edit_context is not None:
        metadata[EDIT_CONTEXT_METADATA_KEY] = edit_context.to_metadata()
    return metadata or None


def metadata_for_assistant_question(
    question_data: Mapping[str, Any],
) -> JsonObject | None:
    normalized = normalize_structured_question_payload(question_data)
    question_id = normalized.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        return None
    return {ASSISTANT_QUESTION_ID_METADATA_KEY: question_id}


def structured_question_payload_from_tool_arguments(
    arguments: object,
) -> JsonObject | None:
    arguments_map = _mapping_value(arguments)
    if arguments_map is None:
        return None
    normalized = normalize_structured_question_payload(arguments_map)
    question_id = normalized.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        return None
    return normalized


def make_persisted_assistant_tool_call(
    *,
    tool_call_id: str,
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
) -> PersistedAssistantToolCall:
    return PersistedAssistantToolCall(
        id=tool_call_id,
        name=tool_name,
        arguments=dict(arguments or {}),
    )


def persisted_assistant_tool_call_from_runtime(
    tool_call: RuntimeToolCall | PersistedAssistantToolCall,
    *,
    arguments: Mapping[str, Any],
) -> PersistedAssistantToolCall:
    if isinstance(tool_call, PersistedAssistantToolCall):
        return tool_call.model_copy(update={"arguments": dict(arguments)})
    return make_persisted_assistant_tool_call(
        tool_call_id=str(tool_call.id),
        tool_name=str(tool_call.function.name),
        arguments=arguments,
    )


def persisted_assistant_tool_call_from_raw(
    value: object,
) -> PersistedAssistantToolCall | None:
    value_map = _mapping_value(value)
    if value_map is None:
        return None
    try:
        return PersistedAssistantToolCall.model_validate(value_map)
    except ValidationError:
        return None


def tool_calls_from_message(message: object) -> tuple[PersistedAssistantToolCall, ...]:
    raw_tool_calls: object = None
    if isinstance(message, Mapping):
        message_map = cast(Mapping[str, object], message)
        raw_tool_calls = message_map.get("tool_calls")
    else:
        raw_tool_calls = getattr(message, "tool_calls", None)

    tool_call_values = _object_sequence(raw_tool_calls)
    if tool_call_values is None:
        return tuple()
    parsed: list[PersistedAssistantToolCall] = []
    for raw_tool_call in tool_call_values:
        tool_call = persisted_assistant_tool_call_from_raw(raw_tool_call)
        if tool_call is not None:
            parsed.append(tool_call)
    return tuple(parsed)


def _text_from_scalar(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip() if not isinstance(value, str) else value.strip()
    return text or None


def tool_call_ids(tool_calls: Sequence[PersistedAssistantToolCall]) -> set[str]:
    return {tool_call.id for tool_call in tool_calls if tool_call.id}


def latest_tool_call_arguments(
    message: object,
    *,
    tool_name: str,
) -> JsonObject | None:
    for tool_call in reversed(tool_calls_from_message(message)):
        if tool_call.name == tool_name:
            return tool_call.arguments
    return None
