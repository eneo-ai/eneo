from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.main.exceptions import BadRequestException

ASSISTANT_SNAPSHOT_SCHEMA_VERSION = 1
_ASSISTANT_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "assistant_id",
        "origin",
        "instructions",
        "completion_model",
        "completion_model_kwargs",
        "knowledge_refs",
        "execution_surface_hash",
    }
)
_COMPLETION_MODEL_FIELDS = frozenset({"id", "name", "nickname", "litellm_model_name"})
_KNOWLEDGE_REF_FIELDS = frozenset({"kind", "id", "name"})


def build_assistant_execution_snapshot(
    *, assistant: Any | None
) -> FlowPersistedJsonObject | None:
    """Capture the assistant execution surface used by published flow versions."""
    if assistant is None:
        return None
    assistant_id = getattr(assistant, "id", None)
    if assistant_id is None:
        return None

    knowledge_refs = _assistant_knowledge_snapshot(assistant)
    snapshot: FlowPersistedJsonObject = {
        "schema_version": ASSISTANT_SNAPSHOT_SCHEMA_VERSION,
        "assistant_id": str(assistant_id),
        "origin": _enum_value(getattr(assistant, "origin", None)),
        "instructions": _assistant_instructions(assistant),
        "completion_model": _completion_model_snapshot(
            getattr(assistant, "completion_model", None)
        ),
        "completion_model_kwargs": _model_kwargs_snapshot(
            getattr(assistant, "completion_model_kwargs", None)
        ),
        "knowledge_refs": knowledge_refs,
    }
    snapshot["execution_surface_hash"] = canonical_json_hash(
        _execution_surface_from_snapshot(snapshot)
    )
    return snapshot


def assistant_execution_surface_hash(snapshot: dict[str, Any]) -> str:
    return canonical_json_hash(_execution_surface_from_snapshot(snapshot))


def validate_assistant_execution_snapshot(
    *,
    snapshot: Mapping[str, object],
    assistant_id: UUID,
) -> FlowPersistedJsonObject:
    raw_keys = set(cast(Mapping[object, object], snapshot))
    if not all(isinstance(key, str) for key in raw_keys):
        raise BadRequestException("Assistant snapshot contains unsupported fields.")
    snapshot_keys = cast(set[str], raw_keys)
    missing_fields = _ASSISTANT_SNAPSHOT_FIELDS - snapshot_keys
    if missing_fields:
        raise BadRequestException(
            "Assistant snapshot is missing required fields: "
            f"{', '.join(sorted(missing_fields))}."
        )
    unsupported_fields = snapshot_keys - _ASSISTANT_SNAPSHOT_FIELDS
    if unsupported_fields:
        raise BadRequestException(
            "Assistant snapshot contains unsupported fields: "
            f"{', '.join(sorted(unsupported_fields))}."
        )

    schema_version = snapshot["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != ASSISTANT_SNAPSHOT_SCHEMA_VERSION
    ):
        raise BadRequestException("Assistant snapshot schema_version is unsupported.")

    snapshot_assistant_id = snapshot["assistant_id"]
    if not isinstance(snapshot_assistant_id, str):
        raise BadRequestException("Assistant snapshot assistant_id is invalid.")
    try:
        parsed_assistant_id = UUID(snapshot_assistant_id)
    except ValueError as exc:
        raise BadRequestException(
            "Assistant snapshot assistant_id is invalid."
        ) from exc
    if parsed_assistant_id != assistant_id:
        raise BadRequestException(
            "Assistant snapshot assistant_id does not match the flow step."
        )

    if not _is_optional_string(snapshot["origin"]):
        raise BadRequestException("Assistant snapshot origin is invalid.")
    if not _is_optional_string(snapshot["instructions"]):
        raise BadRequestException("Assistant snapshot instructions are invalid.")
    _validate_completion_model(snapshot["completion_model"])

    completion_model_kwargs = snapshot["completion_model_kwargs"]
    if not isinstance(completion_model_kwargs, dict):
        raise BadRequestException(
            "Assistant snapshot completion_model_kwargs is invalid."
        )
    if not _is_json_value(cast(object, completion_model_kwargs)):
        raise BadRequestException(
            "Assistant snapshot completion_model_kwargs is invalid."
        )
    _validate_knowledge_refs(snapshot["knowledge_refs"])

    stored_hash = snapshot["execution_surface_hash"]
    if not (
        isinstance(stored_hash, str)
        and len(stored_hash) == 64
        and all(character in "0123456789abcdef" for character in stored_hash)
    ):
        raise BadRequestException(
            "Assistant snapshot execution_surface_hash must be a lowercase SHA-256 hash."
        )

    validated_snapshot = cast(FlowPersistedJsonObject, dict(snapshot))
    if stored_hash != assistant_execution_surface_hash(validated_snapshot):
        raise BadRequestException(
            "Assistant snapshot execution_surface_hash does not match its payload."
        )
    return validated_snapshot


def _is_optional_string(value: object) -> bool:
    return value is None or isinstance(value, str)


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


def _validate_completion_model(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise BadRequestException("Assistant snapshot completion_model is invalid.")
    completion_model = cast(dict[str, object], value)
    if set(completion_model) != set(_COMPLETION_MODEL_FIELDS) or not all(
        _is_optional_string(field_value) for field_value in completion_model.values()
    ):
        raise BadRequestException("Assistant snapshot completion_model is invalid.")


def _validate_knowledge_refs(value: object) -> None:
    if not isinstance(value, list):
        raise BadRequestException("Assistant snapshot knowledge_refs is invalid.")
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            raise BadRequestException("Assistant snapshot knowledge_refs is invalid.")
        knowledge_ref = cast(dict[str, object], item)
        if (
            set(knowledge_ref) != set(_KNOWLEDGE_REF_FIELDS)
            or not isinstance(knowledge_ref.get("kind"), str)
            or not isinstance(knowledge_ref.get("id"), str)
            or not _is_optional_string(knowledge_ref.get("name"))
        ):
            raise BadRequestException("Assistant snapshot knowledge_refs is invalid.")


def _execution_surface_from_snapshot(
    snapshot: dict[str, Any],
) -> FlowPersistedJsonObject:
    """Return only fields that affect execution semantics.

    Display labels are intentionally excluded unless they are part of the LLM
    execution surface. This keeps harmless UI renames from invalidating published
    versions while still catching prompt, model, and knowledge behavior drift.
    """
    raw_completion_model = snapshot.get("completion_model")
    completion_model = (
        cast(dict[str, Any], raw_completion_model)
        if isinstance(raw_completion_model, dict)
        else None
    )
    return {
        "schema_version": snapshot.get("schema_version"),
        "assistant_id": snapshot.get("assistant_id"),
        "instructions": snapshot.get("instructions"),
        "completion_model": _completion_model_execution_surface(completion_model),
        "completion_model_kwargs": snapshot.get("completion_model_kwargs") or {},
        "knowledge_refs": _knowledge_execution_surface(snapshot.get("knowledge_refs")),
    }


def _assistant_instructions(assistant: Any) -> str | None:
    get_prompt_text = getattr(assistant, "get_prompt_text", None)
    if callable(get_prompt_text):
        text = get_prompt_text()
        return text if isinstance(text, str) else None

    prompt = getattr(assistant, "prompt", None)
    text = getattr(prompt, "text", None)
    return text if isinstance(text, str) else None


def _completion_model_snapshot(model: Any | None) -> FlowPersistedJsonObject | None:
    if model is None:
        return None
    return {
        "id": str(getattr(model, "id")) if getattr(model, "id", None) else None,
        "name": getattr(model, "name", None),
        "nickname": getattr(model, "nickname", None),
        "litellm_model_name": getattr(model, "litellm_model_name", None),
    }


def _completion_model_execution_surface(
    model: dict[str, Any] | None,
) -> FlowPersistedJsonObject | None:
    if model is None:
        return None
    return {
        "id": model.get("id"),
        "litellm_model_name": model.get("litellm_model_name"),
    }


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
                    "name": getattr(resource, "name", None),
                }
            )
    return refs


def _knowledge_execution_surface(value: Any) -> list[FlowPersistedJsonObject]:
    refs = cast(list[Any], value) if isinstance(value, list) else []
    normalized: list[FlowPersistedJsonObject] = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, Any], item)
        normalized.append(
            {
                "kind": item_dict.get("kind"),
                "id": item_dict.get("id"),
            }
        )
    return sorted(normalized, key=lambda item: (str(item["kind"]), str(item["id"])))


def _enum_value(value: Any) -> str | None:
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return value if isinstance(value, str) else None
