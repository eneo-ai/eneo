from __future__ import annotations

import math
from datetime import date
from typing import Any, cast

from intric.main.exceptions import BadRequestException

_RUN_FIELD_TYPE_LEGACY_NORMALIZATION = {
    "string": "text",
    "email": "text",
    "textarea": "text",
}

_OrderedField = tuple[int, int, dict[str, Any]]


def _flow_payload_error(
    *,
    message: str,
    code: str,
    field_name: str | None = None,
    field_type: str | None = None,
) -> BadRequestException:
    context: dict[str, object] = {}
    if field_name is not None:
        context["field_name"] = field_name
    if field_type is not None:
        context["field_type"] = field_type
    return BadRequestException(message, code=code, context=context or None)


def normalize_and_validate_flow_run_payload(
    *,
    metadata_json: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    form_schema = (
        metadata_json.get("form_schema") if metadata_json is not None else None
    )
    if not isinstance(form_schema, dict):
        return payload

    form_schema_dict = cast(dict[str, Any], form_schema)
    fields_raw = form_schema_dict.get("fields")
    if not isinstance(fields_raw, list):
        return payload

    fields_list = cast(list[Any], fields_raw)
    if len(fields_list) == 0:
        return payload
    normalized_payload = dict(payload or {})

    ordered_fields: list[_OrderedField] = []
    for index, raw in enumerate(fields_list):
        if not isinstance(raw, dict):
            continue
        field = cast(dict[str, Any], raw)
        order = field.get("order")
        if not isinstance(order, int):
            order = index + 1
        ordered_fields.append((order, index, field))
    ordered_fields.sort(key=lambda item: (item[0], item[1]))

    for _order, _index, field in ordered_fields:
        field_name = field.get("name")
        if not isinstance(field_name, str) or not field_name.strip():
            continue
        key = field_name.strip()
        required = bool(field.get("required"))
        raw_type = field.get("type")
        field_type = (
            raw_type.strip().casefold()
            if isinstance(raw_type, str) and raw_type.strip()
            else "text"
        )
        field_type = _RUN_FIELD_TYPE_LEGACY_NORMALIZATION.get(field_type, field_type)
        options_raw = field.get("options")
        options = (
            [
                option.strip()
                for option in cast(list[Any], options_raw)
                if isinstance(option, str) and option.strip()
            ]
            if isinstance(options_raw, list)
            else []
        )

        if key not in normalized_payload:
            if required:
                raise _flow_payload_error(
                    message=f"Missing required input field '{key}'.",
                    code="flow_input_required_field_missing",
                    field_name=key,
                    field_type=field_type,
                )
            continue

        value = normalized_payload.get(key)
        if value is None:
            if required:
                raise _flow_payload_error(
                    message=f"Missing required input field '{key}'.",
                    code="flow_input_required_field_missing",
                    field_name=key,
                    field_type=field_type,
                )
            continue

        if field_type == "number":
            normalized_payload[key] = coerce_number_field(
                field_name=key,
                value=value,
                required=required,
            )
            continue

        if field_type == "date":
            normalized_payload[key] = coerce_date_field(
                field_name=key,
                value=value,
                required=required,
            )
            continue

        if field_type == "select":
            normalized_payload[key] = coerce_select_field(
                field_name=key,
                value=value,
                options=options,
                required=required,
            )
            continue

        if field_type == "multiselect":
            normalized_payload[key] = coerce_multiselect_field(
                field_name=key,
                value=value,
                options=options,
                required=required,
            )
            continue

        normalized_payload[key] = coerce_text_field(
            field_name=key,
            value=value,
            required=required,
        )

    return normalized_payload


def coerce_text_field(*, field_name: str, value: Any, required: bool) -> str:
    if isinstance(value, str):
        text_value = value
    elif isinstance(value, (int, float, bool)):
        text_value = str(value)
    else:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a string.",
            code="flow_input_type_mismatch",
            field_name=field_name,
            field_type="text",
        )
    if required and text_value.strip() == "":
        raise _flow_payload_error(
            message=f"Field '{field_name}' cannot be empty.",
            code="flow_input_required_field_empty",
            field_name=field_name,
            field_type="text",
        )
    return text_value


def coerce_number_field(
    *, field_name: str, value: Any, required: bool
) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number_value: int | float = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            if required:
                raise _flow_payload_error(
                    message=f"Field '{field_name}' cannot be empty.",
                    code="flow_input_required_field_empty",
                    field_name=field_name,
                    field_type="number",
                )
            return None
        try:
            lowered = stripped.casefold()
            if "." in stripped or "e" in lowered:
                number_value = float(stripped)
            else:
                number_value = int(stripped)
        except ValueError as exc:
            raise _flow_payload_error(
                message=f"Field '{field_name}' must be a valid number.",
                code="flow_input_invalid_number",
                field_name=field_name,
                field_type="number",
            ) from exc
    else:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a valid number.",
            code="flow_input_invalid_number",
            field_name=field_name,
            field_type="number",
        )

    if isinstance(number_value, float) and not math.isfinite(number_value):
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a finite number.",
            code="flow_input_invalid_number",
            field_name=field_name,
            field_type="number",
        )
    return number_value


def coerce_date_field(*, field_name: str, value: Any, required: bool) -> str | None:
    if isinstance(value, date):
        date_value = value.isoformat()
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            if required:
                raise _flow_payload_error(
                    message=f"Field '{field_name}' cannot be empty.",
                    code="flow_input_required_field_empty",
                    field_name=field_name,
                    field_type="date",
                )
            return None
        try:
            date.fromisoformat(stripped)
        except ValueError as exc:
            raise _flow_payload_error(
                message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
                code="flow_input_invalid_date",
                field_name=field_name,
                field_type="date",
            ) from exc
        date_value = stripped
    else:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
            code="flow_input_invalid_date",
            field_name=field_name,
            field_type="date",
        )
    return date_value


def coerce_select_field(
    *,
    field_name: str,
    value: Any,
    options: list[str],
    required: bool,
) -> str | None:
    if not isinstance(value, str):
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a string.",
            code="flow_input_type_mismatch",
            field_name=field_name,
            field_type="select",
        )
    selected = value.strip()
    if selected == "":
        if required:
            raise _flow_payload_error(
                message=f"Field '{field_name}' cannot be empty.",
                code="flow_input_required_field_empty",
                field_name=field_name,
                field_type="select",
            )
        return None
    if options and selected not in options:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be one of the configured options.",
            code="flow_input_invalid_option",
            field_name=field_name,
            field_type="select",
        )
    return selected


def coerce_multiselect_field(
    *,
    field_name: str,
    value: Any,
    options: list[str],
    required: bool,
) -> list[str]:
    raw_values: list[str]
    if isinstance(value, list):
        items = cast(list[Any], value)
        raw_values = []
        for item in items:
            if not isinstance(item, str):
                raise _flow_payload_error(
                    message=f"Field '{field_name}' must contain only string options.",
                    code="flow_input_invalid_multiselect_value",
                    field_name=field_name,
                    field_type="multiselect",
                )
            stripped_item = item.strip()
            if stripped_item:
                raw_values.append(stripped_item)
    elif isinstance(value, str):
        raw_values = [item.strip() for item in value.split(",") if item.strip()]
    else:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be an array of strings.",
            code="flow_input_invalid_multiselect_type",
            field_name=field_name,
            field_type="multiselect",
        )

    if required and len(raw_values) == 0:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must contain at least one value.",
            code="flow_input_required_field_empty",
            field_name=field_name,
            field_type="multiselect",
        )
    if options:
        invalid = [item for item in raw_values if item not in options]
        if invalid:
            raise _flow_payload_error(
                message=f"Field '{field_name}' contains invalid option values.",
                code="flow_input_invalid_option",
                field_name=field_name,
                field_type="multiselect",
            )
    return raw_values
