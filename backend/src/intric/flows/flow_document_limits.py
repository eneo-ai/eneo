"""Tenant overrides and hard ceilings for generated flow documents."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from intric.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
)
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger

logger = get_logger(__name__)


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


def _extract_document_render_limits(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}

    limits = tenant_flow_settings.get("document_render_limits")
    if not isinstance(limits, dict):
        return {}

    return dict(cast(dict[str, Any], limits))


def _parse_limit(value: Any, field_name: str) -> int:
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


def validate_flow_document_render_limits_object(limits: Any) -> dict[str, Any]:
    if not isinstance(limits, dict):
        raise BadRequestException(
            "flow_settings.document_render_limits must be an object"
        )

    limits_dict = cast(dict[str, Any], limits)
    for key, value in limits_dict.items():
        if key not in _FIELD_NAMES:
            raise BadRequestException(f"Unsupported document render limit: {key}.")
        _parse_limit(value, key)

    return limits_dict


def resolve_flow_document_render_limits(
    tenant_flow_settings: dict[str, Any] | None,
) -> DocumentRenderLimits:
    overrides = _extract_document_render_limits(tenant_flow_settings)
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
    current_flow_settings: dict[str, Any] | None,
    *,
    remove_keys: set[str] | None = None,
    **updates: int,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    next_limits = _extract_document_render_limits(result)

    for key, value in updates.items():
        if key not in _FIELD_NAMES:
            raise BadRequestException(f"Unsupported document render limit: {key}.")
        next_limits[key] = _parse_limit(value, key)

    for key in remove_keys or ():
        if key not in _FIELD_NAMES:
            raise BadRequestException(f"Unsupported document render limit: {key}.")
        next_limits.pop(key, None)

    if next_limits:
        result["document_render_limits"] = next_limits
    else:
        result.pop("document_render_limits", None)
    return result
