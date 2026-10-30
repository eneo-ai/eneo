"""Versioned assistant identity for published execution.

V2 covers model binding and authored settings, not provider endpoint settings or
capability-filtered kwargs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant


class _SnapshotValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class CompletionModelBinding(_SnapshotValue):
    model_id: str
    provider_id: str
    provider_type: str = Field(min_length=1)
    resolved_route: str = Field(min_length=1)

    @field_validator("model_id", "provider_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return str(UUID(value))


class SnapshotKnowledgeRef(_SnapshotValue):
    kind: Literal["collection", "website", "integration_knowledge"]
    id: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return str(UUID(value))


class SnapshotAttachment(_SnapshotValue):
    file_id: str
    checksum: str = Field(min_length=1)

    @field_validator("file_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return str(UUID(value))


class SnapshotModelKwargs(ModelKwargs):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class AssistantExecutionSurfaceV2(_SnapshotValue):
    schema_version: Literal[2]
    assistant_id: str
    origin: Literal["user", "flow_managed"]
    instructions: str | None
    completion_model: CompletionModelBinding | None
    completion_model_kwargs: SnapshotModelKwargs
    knowledge_refs: list[SnapshotKnowledgeRef]
    attachments: list[SnapshotAttachment]
    inline_file_text: bool

    @field_validator("assistant_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("knowledge_refs")
    @classmethod
    def canonical_knowledge(
        cls, refs: list[SnapshotKnowledgeRef]
    ) -> list[SnapshotKnowledgeRef]:
        return sorted(refs, key=lambda ref: (ref.kind, ref.id))

    def execution_surface(self) -> FlowPersistedJsonObject:
        payload = self.model_dump(mode="json", exclude={"execution_surface_hash"})
        payload["completion_model_kwargs"] = self.completion_model_kwargs.model_dump(
            mode="json", exclude_none=True
        )
        if not _is_json_value(payload):
            raise ValueError("Assistant snapshot contains invalid JSON values.")
        return payload


class AssistantExecutionSnapshotV2(AssistantExecutionSurfaceV2):
    execution_surface_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def build_assistant_execution_snapshot(
    *, assistant: Assistant
) -> FlowPersistedJsonObject:
    """Capture the assistant execution surface used by published flow versions."""
    model = assistant.completion_model
    surface = AssistantExecutionSurfaceV2.model_validate(
        {
            "schema_version": 2,
            "assistant_id": str(assistant.id),
            "origin": assistant.origin.value,
            "instructions": assistant.get_prompt_text(),
            "completion_model": None
            if model is None
            else {
                "model_id": str(model.id),
                "provider_id": str(model.provider_id),
                "provider_type": model.provider_type,
                "resolved_route": model.get_model_route(),
            },
            "completion_model_kwargs": _model_kwargs_snapshot(
                assistant.completion_model_kwargs
            ),
            "knowledge_refs": _assistant_knowledge_snapshot(assistant),
            "attachments": [
                {"file_id": str(file.id), "checksum": file.checksum}
                for file in assistant.attachments
            ],
            "inline_file_text": assistant.inline_file_text,
        }
    ).execution_surface()
    return {**surface, "execution_surface_hash": canonical_json_hash(surface)}


def _require_v2_snapshot(snapshot: Mapping[str, object] | None) -> None:
    version = snapshot.get("schema_version") if snapshot is not None else None
    if type(version) is not int or version != 2:
        raise BadRequestException(
            "Assistant snapshot is missing or uses an unsupported schema_version. Republish the flow before running it.",
            code=FlowApiErrorCode.ASSISTANT_SNAPSHOT_REPUBLISH_REQUIRED.value,
        )


def assistant_execution_surface_hash(snapshot: dict[str, Any]) -> str:
    _require_v2_snapshot(snapshot)
    try:
        surface = AssistantExecutionSurfaceV2.model_validate(
            {
                key: value
                for key, value in snapshot.items()
                if key != "execution_surface_hash"
            }
        ).execution_surface()
    except (ValidationError, ValueError) as exc:
        raise BadRequestException("Assistant snapshot v2 is invalid.") from exc
    return canonical_json_hash(surface)


def validate_assistant_execution_snapshot(
    *,
    snapshot: Mapping[str, object] | None,
    assistant_id: UUID,
) -> FlowPersistedJsonObject:
    _require_v2_snapshot(snapshot)
    try:
        parsed = AssistantExecutionSnapshotV2.model_validate(snapshot)
        surface = parsed.execution_surface()
    except (ValidationError, ValueError) as exc:
        raise BadRequestException("Assistant snapshot v2 is invalid.") from exc
    if parsed.assistant_id != str(assistant_id):
        raise BadRequestException(
            "Assistant snapshot assistant_id does not match the flow step."
        )
    if parsed.execution_surface_hash != canonical_json_hash(surface):
        raise BadRequestException(
            "Assistant snapshot execution_surface_hash does not match its payload."
        )
    return {**surface, "execution_surface_hash": parsed.execution_surface_hash}


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, str | bool | int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in cast(list[object], value))
    if isinstance(value, dict):
        entries = cast(dict[object, object], value)
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in entries.items()
        )
    return False


def _model_kwargs_snapshot(model_kwargs: Any | None) -> FlowPersistedJsonObject:
    if model_kwargs is None:
        return {}
    if hasattr(model_kwargs, "model_dump"):
        return cast(
            FlowPersistedJsonObject,
            model_kwargs.model_dump(mode="json", exclude_none=True),
        )
    if isinstance(model_kwargs, dict):
        raw_kwargs = cast(dict[object, object], model_kwargs)
        return {
            str(key): value for key, value in raw_kwargs.items() if value is not None
        }
    return {}


def _assistant_knowledge_snapshot(assistant: Any) -> list[FlowPersistedJsonObject]:
    refs: list[FlowPersistedJsonObject] = []
    for attr, kind in (
        ("collections", "collection"),
        ("websites", "website"),
        ("integration_knowledge_list", "integration_knowledge"),
    ):
        for resource in getattr(assistant, attr, []) or []:
            refs.append(
                {
                    "kind": kind,
                    "id": str(getattr(resource, "id")),
                }
            )
    return refs
