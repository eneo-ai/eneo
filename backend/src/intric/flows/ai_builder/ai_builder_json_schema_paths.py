from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

_COMPOSITE_SCHEMA_KEYWORDS = ("allOf", "anyOf", "oneOf")


def missing_structured_output_path(
    contract: dict[str, Any],
    field_path: str,
    *,
    require_array_index: bool = False,
) -> str | None:
    """Return the first missing segment for a JSON-schema-backed structured path.

    When ``require_array_index`` is false, array item properties may be traversed
    without an explicit numeric index. Runtime template validation keeps that
    lenient behavior for backwards compatibility with existing flow bindings.
    """

    current: dict[str, Any] | None = contract
    traversed: list[str] = []
    for part in field_path.split("."):
        traversed.append(part)
        if not isinstance(current, dict):
            return ".".join(traversed)

        schema_type = current.get("type")
        if schema_type == "array":
            if require_array_index and not part.isdigit():
                return ".".join(traversed)
            current = _dict_or_none(current.get("items"))
            if current is None:
                return ".".join(traversed)
            if part.isdigit():
                continue

        properties = resolve_schema_properties(current)
        if part not in properties:
            return ".".join(traversed)
        current = _dict_or_none(properties[part])

    return None


def schema_property_names(schema: dict[str, Any]) -> set[str]:
    """Return reachable property names for structured-reference suggestions."""

    names: set[str] = set()
    properties = resolve_schema_properties(schema)
    names.update(properties.keys())
    for value in properties.values():
        if not isinstance(value, dict):
            continue
        child_properties = resolve_schema_properties(cast(dict[str, Any], value))
        names.update(child_properties.keys())
    return names


def top_level_schema_property_names(schema: dict[str, Any]) -> list[str]:
    """Return declared top-level property names in schema order."""

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []

    property_map = cast(dict[str, object], properties)
    names: list[str] = []
    for raw_name in property_map:
        name = str(raw_name).strip()
        if name:
            names.append(name)
    return names


def resolve_schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    _merge_schema_properties(properties, [schema])
    return properties


def _merge_schema_properties(
    properties: dict[str, Any],
    schemas: Iterable[dict[str, Any]],
) -> None:
    for schema in schemas:
        direct = schema.get("properties")
        if isinstance(direct, dict):
            properties.update(cast(dict[str, Any], direct))
        for keyword in _COMPOSITE_SCHEMA_KEYWORDS:
            subschemas = schema.get(keyword)
            if not isinstance(subschemas, list):
                continue
            nested_schemas: list[dict[str, Any]] = []
            for subschema in cast(list[object], subschemas):
                if isinstance(subschema, dict):
                    nested_schemas.append(cast(dict[str, Any], subschema))
            _merge_schema_properties(properties, nested_schemas)


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None
