from __future__ import annotations

from typing import Any, cast
import re

from intric.flows.domain.flow import FlowStep, JsonObject
from intric.flows.flow_variable_definitions import RESERVED_RUNTIME_VARIABLES_NORMALIZED
from intric.main.exceptions import BadRequestException

_ALLOWED_FORM_FIELD_TYPES = {"text", "multiselect", "number", "date", "select"}
_LEGACY_FORM_FIELD_TYPE_NORMALIZATION = {
    "string": "text",
    "email": "text",
    "textarea": "text",
}
_STEP_ALIAS_PATTERN = re.compile(r"^step_\d+($|[._])")


def validate_form_schema(metadata_json: JsonObject | None) -> None:
    if metadata_json is None:
        return

    form_schema = metadata_json.get("form_schema")
    if form_schema is None:
        return
    if not isinstance(form_schema, dict):
        raise BadRequestException("metadata_json.form_schema must be an object.")
    form_schema_dict = cast(dict[str, Any], form_schema)

    fields = form_schema_dict.get("fields")
    if not isinstance(fields, list):
        raise BadRequestException("metadata_json.form_schema.fields must be a list.")

    seen_names: set[str] = set()
    seen_orders: set[int] = set()
    for index, field in enumerate(cast(list[object], fields)):
        if not isinstance(field, dict):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}] must be an object."
            )
        field_dict = cast(dict[str, Any], field)
        field_name = field_dict.get("name")
        if not isinstance(field_name, str) or not field_name.strip():
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name must be a non-empty string."
            )
        normalized_name = field_name.strip().casefold()
        if normalized_name in seen_names:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name must be unique."
            )
        if "." in field_name:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name cannot contain '.'."
            )
        if "{{" in field_name or "}}" in field_name:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name cannot contain template delimiters."
            )
        if normalized_name in RESERVED_RUNTIME_VARIABLES_NORMALIZED:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name uses a reserved variable alias."
            )
        if _STEP_ALIAS_PATTERN.match(normalized_name):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name cannot use reserved step alias format."
            )
        seen_names.add(normalized_name)
        field_type = field_dict.get("type")
        if not isinstance(field_type, str) or not field_type.strip():
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].type must be a non-empty string."
            )
        normalized_type = field_type.strip().casefold()
        if normalized_type not in _ALLOWED_FORM_FIELD_TYPES:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].type must be one of "
                f"{sorted(_ALLOWED_FORM_FIELD_TYPES)}."
            )
        if "required" in field_dict and not isinstance(field_dict["required"], bool):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].required must be a boolean."
            )
        if "order" in field_dict:
            if not isinstance(field_dict["order"], int):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].order must be an integer."
                )
            order_value = field_dict["order"]
            if order_value < 1:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].order must be >= 1."
                )
            if order_value in seen_orders:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].order must be unique."
                )
            seen_orders.add(order_value)
        options = field_dict.get("options")
        if normalized_type == "multiselect":
            if options is None or not isinstance(options, list):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].options must be a list for multiselect."
                )
            normalized_options: set[str] = set()
            for option_index, option in enumerate(cast(list[object], options)):
                if not isinstance(option, str) or not option.strip():
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                        "must be a non-empty string."
                    )
                option_key = option.strip().casefold()
                if option_key in normalized_options:
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                        "must be unique."
                    )
                normalized_options.add(option_key)
        elif normalized_type == "select":
            if options is not None and not isinstance(options, list):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].options must be a list for select."
                )
            if isinstance(options, list):
                normalized_options: set[str] = set()
                for option_index, option in enumerate(cast(list[object], options)):
                    if not isinstance(option, str) or not option.strip():
                        raise BadRequestException(
                            f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                            "must be a non-empty string."
                        )
                    option_key = option.strip().casefold()
                    if option_key in normalized_options:
                        raise BadRequestException(
                            f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                            "must be unique."
                        )
                    normalized_options.add(option_key)
        elif options is not None:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options is only valid for select or multiselect."
            )


def normalize_legacy_form_schema(metadata_json: JsonObject | None) -> JsonObject | None:
    if metadata_json is None:
        return None
    form_schema_obj = metadata_json.get("form_schema")
    if not isinstance(form_schema_obj, dict):
        return metadata_json
    form_schema = cast(dict[str, Any], form_schema_obj)
    fields_obj = form_schema.get("fields")
    if not isinstance(fields_obj, list):
        return metadata_json
    fields = cast(list[object], fields_obj)

    changed = False
    normalized_fields: list[object] = []
    for field in fields:
        if not isinstance(field, dict):
            normalized_fields.append(field)
            continue
        field_dict = cast(dict[str, Any], field)
        normalized_field = dict(field_dict)
        raw_type = normalized_field.get("type")
        if isinstance(raw_type, str):
            legacy_target = _LEGACY_FORM_FIELD_TYPE_NORMALIZATION.get(
                raw_type.strip().casefold()
            )
            if legacy_target is not None and legacy_target != raw_type:
                normalized_field["type"] = legacy_target
                changed = True
        normalized_fields.append(normalized_field)

    if not changed:
        return metadata_json

    normalized_form_schema = dict(form_schema)
    normalized_form_schema["fields"] = normalized_fields
    normalized_metadata = dict(metadata_json)
    normalized_metadata["form_schema"] = normalized_form_schema
    return normalized_metadata


def validate_variable_alias_collisions(
    *,
    steps: list[FlowStep],
    metadata_json: JsonObject | None,
) -> None:
    normalized_reserved = RESERVED_RUNTIME_VARIABLES_NORMALIZED
    field_names: dict[str, str] = {}

    form_schema_obj = metadata_json.get("form_schema") if metadata_json else None
    if isinstance(form_schema_obj, dict):
        form_schema = cast(dict[str, Any], form_schema_obj)
        fields_obj = form_schema.get("fields")
    else:
        fields_obj = None
    if isinstance(fields_obj, list):
        for index, field in enumerate(cast(list[object], fields_obj)):
            if not isinstance(field, dict):
                continue
            field_dict = cast(dict[str, Any], field)
            raw_name = field_dict.get("name")
            if not isinstance(raw_name, str):
                continue
            normalized = raw_name.strip().casefold()
            if not normalized:
                continue
            if normalized in normalized_reserved:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name is reserved."
                )
            if _STEP_ALIAS_PATTERN.match(normalized):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name conflicts with reserved step alias namespace."
                )
            field_names[normalized] = raw_name.strip()

    for step in steps:
        raw_name = step.user_description
        if raw_name is None:
            continue
        normalized = raw_name.strip().casefold()
        if not normalized:
            continue
        if normalized in normalized_reserved:
            raise BadRequestException(
                f"Step {step.step_order} name '{raw_name}' uses a reserved variable alias."
            )
        if _STEP_ALIAS_PATTERN.match(normalized):
            raise BadRequestException(
                f"Step {step.step_order} name '{raw_name}' conflicts with reserved step alias namespace."
            )
        if normalized in field_names:
            raise BadRequestException(
                f"Step {step.step_order} name '{raw_name}' conflicts with form field name '{field_names[normalized]}'."
            )
