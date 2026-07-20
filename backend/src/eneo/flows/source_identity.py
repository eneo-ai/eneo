from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Protocol, TypeVar, cast

_DraftFieldT = TypeVar("_DraftFieldT", bound="RuntimeSourceIdentityDraftField")


class RuntimeSourceIdentityDraftField(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def field_type(self) -> str: ...

    @property
    def item_fields(self) -> Sequence["RuntimeSourceIdentityDraftField"] | None: ...

    def model_copy(
        self: _DraftFieldT,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> _DraftFieldT: ...


RUNTIME_SOURCE_IDENTITY_FIELDS = frozenset({"source_label", "source_file_id"})


def without_runtime_source_identity_draft_fields(
    fields: Sequence[_DraftFieldT],
) -> list[_DraftFieldT]:
    projected_fields: list[_DraftFieldT] = []
    for field in fields:
        if field.field_type != "array":
            projected_fields.append(field)
            continue
        item_fields = [
            item
            for item in field.item_fields or []
            if item.name not in RUNTIME_SOURCE_IDENTITY_FIELDS
        ]
        projected_fields.append(field.model_copy(update={"item_fields": item_fields}))
    return projected_fields


def without_runtime_source_identity_json_fields(
    contract: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if contract is None:
        return None
    projected_contract = deepcopy(contract)
    properties = projected_contract.get("properties")
    if not isinstance(properties, Mapping):
        return projected_contract
    typed_properties = cast(Mapping[str, Any], properties)
    for raw_array_schema in typed_properties.values():
        if not isinstance(raw_array_schema, dict):
            continue
        array_schema = cast(dict[str, Any], raw_array_schema)
        if array_schema.get("type") != "array":
            continue
        item_schema = array_schema.get("items")
        if isinstance(item_schema, dict):
            _remove_identity_fields_from_object_schema(
                cast(dict[str, Any], item_schema)
            )
    return projected_contract


def runtime_source_identity_fields_for_array_items(
    contract: dict[str, Any] | None,
    array_key: str,
) -> frozenset[str]:
    item_schema = _array_item_object_schema(contract, array_key)
    if item_schema is None:
        return frozenset()
    properties = item_schema.get("properties")
    if not isinstance(properties, Mapping):
        return frozenset()
    return frozenset(
        field_name
        for field_name in RUNTIME_SOURCE_IDENTITY_FIELDS
        if field_name in properties
    )


def has_required_runtime_source_identity_fields(
    contract: dict[str, Any] | None,
    array_key: str,
) -> bool:
    item_schema = _array_item_object_schema(contract, array_key)
    if item_schema is None:
        return False
    properties = item_schema.get("properties")
    required = item_schema.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        return False
    for field_name in RUNTIME_SOURCE_IDENTITY_FIELDS:
        field_schema = properties.get(field_name)
        if (
            not isinstance(field_schema, Mapping)
            or field_schema.get("type") != "string"
            or field_name not in required
        ):
            return False
    return True


def _array_item_object_schema(
    contract: dict[str, Any] | None,
    array_key: str,
) -> dict[str, Any] | None:
    if not isinstance(contract, Mapping):
        return None
    properties = contract.get("properties")
    if not isinstance(properties, Mapping):
        return None
    typed_properties = cast(Mapping[str, Any], properties)
    array_schema = typed_properties.get(array_key)
    if not isinstance(array_schema, Mapping):
        return None
    typed_array_schema = cast(Mapping[str, Any], array_schema)
    if typed_array_schema.get("type") != "array":
        return None
    item_schema = typed_array_schema.get("items")
    if not isinstance(item_schema, Mapping):
        return None
    typed_item_schema = cast(Mapping[str, Any], item_schema)
    if typed_item_schema.get("type") != "object":
        return None
    return dict(typed_item_schema)


def _remove_identity_fields_from_object_schema(schema: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        typed_properties = cast(dict[str, Any], properties)
        for field_name in RUNTIME_SOURCE_IDENTITY_FIELDS:
            typed_properties.pop(field_name, None)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [
            field_name
            for field_name in cast(list[object], required)
            if field_name not in RUNTIME_SOURCE_IDENTITY_FIELDS
        ]
