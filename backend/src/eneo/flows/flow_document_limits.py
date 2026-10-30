"""Tenant overrides and hard ceilings for generated flow documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import cast

from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
)
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

_DOCUMENT_RENDER_LIMITS_KEY = "document_render_limits"


# Tenant admins may tune effective limits at runtime, but these hard ceilings
# protect shared worker capacity from pathological generated documents.
FLOW_DOCUMENT_RENDER_HARD_LIMITS = DocumentRenderLimits(
    max_source_chars=5_000_000,
    max_blocks=20_000,
    max_text_chars=5_000_000,
    max_table_rows=50_000,
    max_table_columns=100,
    max_table_cells=500_000,
    max_cell_chars=100_000,
    max_list_items=50_000,
    max_structured_nodes=100_000,
    max_structured_depth=100,
    max_object_fields=1_000,
)


_FIELD_NAMES = tuple(asdict(DEFAULT_DOCUMENT_RENDER_LIMITS))


def _object_mapping(value: object | None) -> Mapping[object, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[object, object], value)


def _extract_document_render_limit_values(
    tenant_flow_settings: object | None,
) -> dict[str, object]:
    settings = _object_mapping(tenant_flow_settings)
    if settings is None:
        return {}

    limits = _object_mapping(settings.get(_DOCUMENT_RENDER_LIMITS_KEY))
    if limits is None:
        return {}

    return {key: value for key, value in limits.items() if isinstance(key, str)}


def _parse_limit(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")

    if value < 1:
        raise BadRequestException(f"{field_name} must be greater than zero.")

    hard_limit = getattr(FLOW_DOCUMENT_RENDER_HARD_LIMITS, field_name)
    if value > hard_limit:
        raise BadRequestException(
            f"{field_name} must be less than or equal to {hard_limit}."
        )

    return value


def validate_flow_document_render_limits_object(
    limits: object,
) -> dict[str, int]:
    limits_mapping = _object_mapping(limits)
    if limits_mapping is None:
        raise BadRequestException(
            "flow_settings.document_render_limits must be an object"
        )

    parsed: dict[str, int] = {}
    for key, value in limits_mapping.items():
        if not isinstance(key, str):
            raise BadRequestException("Document render limit names must be strings.")
        if key not in _FIELD_NAMES:
            raise BadRequestException(f"Unsupported document render limit: {key}.")
        parsed[key] = _parse_limit(value, key)

    return parsed


def resolve_flow_document_render_limits(
    tenant_flow_settings: object | None,
) -> DocumentRenderLimits:
    overrides = _extract_document_render_limit_values(tenant_flow_settings)
    values = asdict(DEFAULT_DOCUMENT_RENDER_LIMITS)

    for key in _FIELD_NAMES:
        if key not in overrides:
            continue
        try:
            values[key] = _parse_limit(overrides[key], key)
        except BadRequestException:
            logger.warning(
                "Ignoring invalid tenant flow document render setting: %s",
                key,
                extra={"value": overrides.get(key)},
            )

    return DocumentRenderLimits(**values)


def apply_flow_document_render_limits_patch(
    current_flow_settings: Mapping[str, object] | None,
    *,
    remove_keys: set[str] | None = None,
    **updates: int,
) -> dict[str, object]:
    result = (
        dict(current_flow_settings)
        if isinstance(current_flow_settings, Mapping)
        else {}
    )
    next_limit_values = _extract_document_render_limit_values(result)
    next_limits: dict[str, object] = dict(next_limit_values)

    for key, value in updates.items():
        if key not in _FIELD_NAMES:
            raise BadRequestException(f"Unsupported document render limit: {key}.")
        next_limits[key] = _parse_limit(value, key)

    for key in remove_keys or ():
        if key not in _FIELD_NAMES:
            raise BadRequestException(f"Unsupported document render limit: {key}.")
        next_limits.pop(key, None)

    if next_limits:
        result[_DOCUMENT_RENDER_LIMITS_KEY] = next_limits
    else:
        result.pop(_DOCUMENT_RENDER_LIMITS_KEY, None)
    return result
