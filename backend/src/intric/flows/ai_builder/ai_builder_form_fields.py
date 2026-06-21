from __future__ import annotations

from typing import Any, cast

from intric.flows.flow_authoring_spec import (
    FormFieldSpec,
)


def extract_form_fields_from_metadata(
    metadata_json: dict[str, Any] | None,
) -> list[FormFieldSpec] | None:
    if not isinstance(metadata_json, dict):
        return None
    form_schema = metadata_json.get("form_schema")
    if not isinstance(form_schema, dict):
        return None
    form_schema_dict = cast(dict[str, Any], form_schema)
    raw_fields_value = form_schema_dict.get("fields")
    if not isinstance(raw_fields_value, list):
        return None
    raw_fields = cast(list[object], raw_fields_value)

    fields: list[FormFieldSpec] = []
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            continue
        raw_field_dict = cast(dict[str, Any], raw_field)
        name = str(raw_field_dict.get("name", "")).strip()
        if not name:
            continue
        label = str(raw_field_dict.get("label", name)).strip() or name
        field_type = str(raw_field_dict.get("type", "text")).strip() or "text"
        options = raw_field_dict.get("options")
        normalized_option_values = (
            cast(list[object], options) if isinstance(options, list) else []
        )
        normalized_options = (
            [str(option) for option in normalized_option_values]
            if isinstance(options, list)
            else None
        )
        fields.append(
            FormFieldSpec(
                name=name,
                type=field_type,
                label=label,
                required=bool(raw_field_dict.get("required", False)),
                options=normalized_options,
            )
        )
    return fields or None
