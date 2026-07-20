from __future__ import annotations

import math
from datetime import date
from typing import Any, cast

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_metadata import FlowMetadata
from eneo.main.exceptions import BadRequestException


def _flow_payload_error(
    *,
    message: str,
    code: FlowApiErrorCode,
    field_name: str | None = None,
    field_type: str | None = None,
) -> BadRequestException:
    context: dict[str, object] = {}
    if field_name is not None:
        context["field_name"] = field_name
    if field_type is not None:
        context["field_type"] = field_type
    return BadRequestException(message, code=code.value, context=context or None)


def normalize_and_validate_flow_run_payload(
    *,
    metadata: FlowMetadata | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    form_schema = metadata.form_schema if metadata is not None else None
    if form_schema is None or len(form_schema.fields) == 0:
        return payload
    normalized_payload = dict(payload or {})

    ordered_fields = sorted(
        enumerate(form_schema.fields),
        key=lambda item: (item[1].order or item[0] + 1, item[0]),
    )

    for _index, field in ordered_fields:
        key = field.name
        required = field.required
        field_type = field.type.value
        options = field.options or []

        if key not in normalized_payload:
            if required:
                raise _flow_payload_error(
                    message=f"Missing required input field '{key}'.",
                    code=FlowApiErrorCode.INPUT_REQUIRED_FIELD_MISSING,
                    field_name=key,
                    field_type=field_type,
                )
            continue

        value = normalized_payload.get(key)
        if value is None:
            if required:
                raise _flow_payload_error(
                    message=f"Missing required input field '{key}'.",
                    code=FlowApiErrorCode.INPUT_REQUIRED_FIELD_MISSING,
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
            code=FlowApiErrorCode.INPUT_TYPE_MISMATCH,
            field_name=field_name,
            field_type="text",
        )
    if required and text_value.strip() == "":
        raise _flow_payload_error(
            message=f"Field '{field_name}' cannot be empty.",
            code=FlowApiErrorCode.INPUT_REQUIRED_FIELD_EMPTY,
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
                    code=FlowApiErrorCode.INPUT_REQUIRED_FIELD_EMPTY,
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
                code=FlowApiErrorCode.INPUT_INVALID_NUMBER,
                field_name=field_name,
                field_type="number",
            ) from exc
    else:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a valid number.",
            code=FlowApiErrorCode.INPUT_INVALID_NUMBER,
            field_name=field_name,
            field_type="number",
        )

    if isinstance(number_value, float) and not math.isfinite(number_value):
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a finite number.",
            code=FlowApiErrorCode.INPUT_INVALID_NUMBER,
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
                    code=FlowApiErrorCode.INPUT_REQUIRED_FIELD_EMPTY,
                    field_name=field_name,
                    field_type="date",
                )
            return None
        try:
            date.fromisoformat(stripped)
        except ValueError as exc:
            raise _flow_payload_error(
                message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
                code=FlowApiErrorCode.INPUT_INVALID_DATE,
                field_name=field_name,
                field_type="date",
            ) from exc
        date_value = stripped
    else:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
            code=FlowApiErrorCode.INPUT_INVALID_DATE,
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
            code=FlowApiErrorCode.INPUT_TYPE_MISMATCH,
            field_name=field_name,
            field_type="select",
        )
    selected = value.strip()
    if selected == "":
        if required:
            raise _flow_payload_error(
                message=f"Field '{field_name}' cannot be empty.",
                code=FlowApiErrorCode.INPUT_REQUIRED_FIELD_EMPTY,
                field_name=field_name,
                field_type="select",
            )
        return None
    if options and selected not in options:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must be one of the configured options.",
            code=FlowApiErrorCode.INPUT_INVALID_OPTION,
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
        items = cast(list[object], value)
        raw_values = []
        for item in items:
            if not isinstance(item, str):
                raise _flow_payload_error(
                    message=f"Field '{field_name}' must contain only string options.",
                    code=FlowApiErrorCode.INPUT_INVALID_MULTISELECT_VALUE,
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
            code=FlowApiErrorCode.INPUT_INVALID_MULTISELECT_TYPE,
            field_name=field_name,
            field_type="multiselect",
        )

    if required and len(raw_values) == 0:
        raise _flow_payload_error(
            message=f"Field '{field_name}' must contain at least one value.",
            code=FlowApiErrorCode.INPUT_REQUIRED_FIELD_EMPTY,
            field_name=field_name,
            field_type="multiselect",
        )
    if options:
        invalid = [item for item in raw_values if item not in options]
        if invalid:
            raise _flow_payload_error(
                message=f"Field '{field_name}' contains invalid option values.",
                code=FlowApiErrorCode.INPUT_INVALID_OPTION,
                field_name=field_name,
                field_type="multiselect",
            )
    return raw_values
