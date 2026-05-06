from __future__ import annotations

import logging
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_new_step_models import (
    MAX_STRUCTURED_FIELD_DEPTH,
    StructuredFieldDraft,
)

logger = logging.getLogger(__name__)


def normalize_structured_field_list(
    value: Any,
    *,
    depth: int = 1,
) -> list[dict[str, Any]] | None:
    """Coerce loose LLM-shaped field hints into strict field drafts."""

    raw_items = _coerce_field_items(value)
    if raw_items is None:
        if value is not None:
            _log_field_list_dropped(reason="unsupported_shape")
        return None

    fields: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items):
        field = _normalize_structured_field_item(
            raw_item,
            fallback_name=f"field_{index + 1}",
            depth=depth,
        )
        if field is not None:
            fields.append(field)
    if not fields:
        _log_field_list_dropped(reason="no_valid_fields")
        return None
    return fields


def _coerce_field_items(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return cast(list[Any], value)
    if isinstance(value, dict):
        raw = cast(dict[str, Any], value)
        if looks_like_structured_field_spec(raw):
            return [raw]
        properties = raw.get("properties")
        if isinstance(properties, dict):
            raw_properties = cast(dict[str, Any], properties)
            return [
                {"name": name, **cast(dict[str, Any], spec)}
                if isinstance(spec, dict)
                else {"name": name, "field_type": _field_type_from_scalar(spec)}
                for name, spec in raw_properties.items()
            ]
        return [
            {"name": name, **cast(dict[str, Any], spec)}
            if isinstance(spec, dict)
            else {"name": name, "field_type": _field_type_from_scalar(spec)}
            for name, spec in raw.items()
        ]
    if isinstance(value, str) and value.strip():
        return [value]
    return None


def _normalize_structured_field_item(
    value: Any,
    *,
    fallback_name: str,
    depth: int,
) -> dict[str, Any] | None:
    if isinstance(value, StructuredFieldDraft):
        return value.model_dump()

    if isinstance(value, str):
        name = _field_name(value, fallback=fallback_name)
        return _strict_field(name=name, field_type="string", description=value)

    if not isinstance(value, dict):
        return None

    raw = cast(dict[str, Any], value)
    if not looks_like_structured_field_spec(raw) and len(raw) == 1:
        name, spec = next(iter(raw.items()))
        if isinstance(spec, dict):
            raw = {"name": name, **cast(dict[str, Any], spec)}
        else:
            raw = {"name": name, "field_type": _field_type_from_scalar(spec)}

    name = _field_name(raw.get("name"), fallback=fallback_name)
    field_type = _normalize_field_type(
        raw.get("field_type") or raw.get("type"),
        raw=raw,
    )
    description = _field_description(raw, fallback=name.replace("_", " "))
    required = raw.get("required")
    normalized: dict[str, Any] = _strict_field(
        name=name,
        field_type=field_type,
        description=description,
        required=required if isinstance(required, bool) else True,
    )

    child_fields = raw.get("fields") or raw.get("properties")
    item_fields = raw.get("item_fields")
    items = raw.get("items")

    if field_type == "object":
        if depth >= MAX_STRUCTURED_FIELD_DEPTH:
            _log_object_downgrade(name=name, depth=depth, reason="max_depth")
            normalized["field_type"] = "string"
            return normalized
        normalized_children = normalize_structured_field_list(
            child_fields,
            depth=depth + 1,
        )
        if normalized_children:
            normalized["fields"] = normalized_children
        else:
            _log_object_downgrade(name=name, depth=depth, reason="missing_fields")
            normalized["field_type"] = "string"
        return normalized

    if field_type == "array":
        if depth >= MAX_STRUCTURED_FIELD_DEPTH:
            return normalized
        normalized_item_fields = normalize_structured_field_list(
            item_fields,
            depth=depth + 1,
        )
        if normalized_item_fields is None:
            normalized_item_fields = _normalize_array_item_fields(
                items,
                depth=depth + 1,
            )
        if normalized_item_fields is None:
            normalized_item_fields = normalize_structured_field_list(
                child_fields,
                depth=depth + 1,
            )
        if normalized_item_fields:
            normalized["item_fields"] = normalized_item_fields
        return normalized

    return normalized


def _normalize_array_item_fields(
    value: Any,
    *,
    depth: int,
) -> list[dict[str, Any]] | None:
    if isinstance(value, dict):
        raw = cast(dict[str, Any], value)
        properties = raw.get("properties")
        if isinstance(properties, dict):
            return normalize_structured_field_list(properties, depth=depth)
        if looks_like_structured_field_spec(raw):
            return normalize_structured_field_list(raw, depth=depth)
    return None


def _strict_field(
    *,
    name: str,
    field_type: str,
    description: str,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "field_type": field_type,
        "description": description,
        "required": required,
    }


def looks_like_structured_field_spec(value: dict[str, Any]) -> bool:
    return bool(
        {
            "name",
            "field_type",
            "type",
            "description",
            "title",
            "fields",
            "item_fields",
            "items",
        }
        & value.keys()
    )


def _field_name(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _field_description(value: dict[str, Any], *, fallback: str) -> str:
    for key in ("description", "title"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return fallback


def _normalize_field_type(value: Any, *, raw: dict[str, Any]) -> str:
    if not isinstance(value, str) or not value.strip():
        if raw.get("fields") is not None or raw.get("properties") is not None:
            return "object"
        if raw.get("item_fields") is not None or raw.get("items") is not None:
            return "array"
        return "string"

    normalized = value.strip().lower()
    aliases = {
        "str": "string",
        "text": "string",
        "integer": "number",
        "float": "number",
        "double": "number",
        "bool": "boolean",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"string", "number", "boolean", "object", "array"}:
        return "string"
    return normalized


def _field_type_from_scalar(value: Any) -> str:
    if isinstance(value, str):
        return _normalize_field_type(value, raw={})
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _log_object_downgrade(*, name: str, depth: int, reason: str) -> None:
    logger.info(
        "ai_builder_structured_field_object_downgraded",
        extra={
            "field_name": name,
            "depth": depth,
            "reason": reason,
        },
    )


def _log_field_list_dropped(*, reason: str) -> None:
    logger.info(
        "ai_builder_structured_field_list_dropped",
        extra={"reason": reason},
    )


__all__ = [
    "looks_like_structured_field_spec",
    "normalize_structured_field_list",
]
