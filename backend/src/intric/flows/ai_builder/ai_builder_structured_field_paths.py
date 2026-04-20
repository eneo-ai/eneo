from __future__ import annotations

from typing import Any, Iterable, Sequence, cast

from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft

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


def missing_draft_field_path(
    fields: Sequence[StructuredFieldDraft],
    field_path: str,
) -> str | None:
    current_fields: Sequence[StructuredFieldDraft] = fields
    current_field: StructuredFieldDraft | None = None
    traversed: list[str] = []
    expecting_index = False

    for segment in field_path.split("."):
        traversed.append(segment)
        if expecting_index:
            if not segment.isdigit():
                return ".".join(traversed)
            if current_field is None:
                return ".".join(traversed)
            item_fields = cast(
                list[StructuredFieldDraft] | None,
                current_field.item_fields,
            )
            if item_fields is None:
                return ".".join(traversed)
            current_fields = item_fields
            expecting_index = False
            continue

        current_field = _find_field(current_fields, segment)
        if current_field is None:
            return ".".join(traversed)

        if current_field.field_type == "array":
            expecting_index = True
        else:
            nested_fields = cast(
                list[StructuredFieldDraft] | None,
                current_field.fields,
            )
            if nested_fields is not None:
                current_fields = nested_fields
            else:
                current_fields = []

    return ".".join(traversed) if expecting_index else None


def schema_property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    properties = resolve_schema_properties(schema)
    names.update(properties.keys())
    for value in properties.values():
        if not isinstance(value, dict):
            continue
        child_properties = resolve_schema_properties(cast(dict[str, Any], value))
        names.update(child_properties.keys())
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


def _find_field(
    fields: Sequence[StructuredFieldDraft],
    name: str,
) -> StructuredFieldDraft | None:
    for field in fields:
        if field.name == name:
            return field
    return None
