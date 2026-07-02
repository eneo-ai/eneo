from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final, cast

from eneo.flows.flow_ai_builder_budget_settings import (
    validate_ai_builder_budget_settings_object,
)
from eneo.flows.flow_document_limits import (
    validate_flow_document_render_limits_object,
)
from eneo.flows.flow_evidence_policy import validate_flow_evidence_policy_object
from eneo.flows.flow_input_limits import validate_flow_input_limits_object
from eneo.flows.flow_retention_policy import (
    normalize_flow_retention_policy_settings,
    validate_flow_retention_policy_object,
)
from eneo.flows.flow_runtime_policy import validate_flow_runtime_policy_object
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

FLOW_SETTINGS_UNKNOWN_TOP_LEVEL_FIELD_CODE: Final[str] = (
    "flow_settings_unknown_top_level_field"
)

FLOW_SETTINGS_INPUT_LIMITS_KEY: Final[str] = "input_limits"
FLOW_SETTINGS_DOCUMENT_RENDER_LIMITS_KEY: Final[str] = "document_render_limits"
FLOW_SETTINGS_RUNTIME_POLICY_KEY: Final[str] = "runtime_policy"
FLOW_SETTINGS_EVIDENCE_POLICY_KEY: Final[str] = "evidence_policy"
FLOW_SETTINGS_RETENTION_POLICY_KEY: Final[str] = "retention_policy"
FLOW_SETTINGS_AI_BUILDER_KEY: Final[str] = "ai_builder"

FLOW_SETTINGS_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_SETTINGS_INPUT_LIMITS_KEY,
        FLOW_SETTINGS_DOCUMENT_RENDER_LIMITS_KEY,
        FLOW_SETTINGS_RUNTIME_POLICY_KEY,
        FLOW_SETTINGS_EVIDENCE_POLICY_KEY,
        FLOW_SETTINGS_RETENTION_POLICY_KEY,
        FLOW_SETTINGS_AI_BUILDER_KEY,
    }
)

# Bounded by distinct unknown key names, not tenants, to avoid log spam from
# historical JSONB rows without hiding newly observed keys.
_warned_unknown_top_level_keys: set[str] = set()


def normalize_flow_settings_object(value: object | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}

    settings = _copy_string_key_mapping(cast(Mapping[object, object], value))
    unknown_fields = set(settings) - FLOW_SETTINGS_TOP_LEVEL_KEYS
    for key in sorted(unknown_fields):
        if key in _warned_unknown_top_level_keys:
            continue
        _warned_unknown_top_level_keys.add(key)
        logger.warning(
            "Ignoring unknown tenant flow_settings top-level key",
            extra={"flow_settings_key": key},
        )
    known_settings = {
        key: settings[key] for key in settings if key in FLOW_SETTINGS_TOP_LEVEL_KEYS
    }
    return normalize_flow_retention_policy_settings(known_settings)


def validate_flow_settings_write(value: object | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BadRequestException(
            "flow_settings must be an object.",
            code="flow_settings_invalid_payload",
        )

    settings = _copy_string_key_mapping(cast(Mapping[object, object], value))
    unknown_fields = set(settings) - FLOW_SETTINGS_TOP_LEVEL_KEYS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise BadRequestException(
            f"flow_settings contains unknown top-level fields: {unknown}",
            code=FLOW_SETTINGS_UNKNOWN_TOP_LEVEL_FIELD_CODE,
        )

    normalized = normalize_flow_settings_object(settings)
    validate_flow_settings_object(normalized)
    return normalized


def validate_flow_settings_object(value: object | None) -> dict[str, Any]:
    settings = normalize_flow_settings_object(value)

    if FLOW_SETTINGS_INPUT_LIMITS_KEY in settings:
        validate_flow_input_limits_object(settings[FLOW_SETTINGS_INPUT_LIMITS_KEY])
    if FLOW_SETTINGS_DOCUMENT_RENDER_LIMITS_KEY in settings:
        validate_flow_document_render_limits_object(
            settings[FLOW_SETTINGS_DOCUMENT_RENDER_LIMITS_KEY]
        )
    if FLOW_SETTINGS_AI_BUILDER_KEY in settings:
        _translate_value_error(
            lambda: validate_ai_builder_budget_settings_object(
                settings[FLOW_SETTINGS_AI_BUILDER_KEY]
            )
        )
    if FLOW_SETTINGS_RETENTION_POLICY_KEY in settings:
        _translate_value_error(
            lambda: validate_flow_retention_policy_object(
                settings[FLOW_SETTINGS_RETENTION_POLICY_KEY]
            )
        )
    if FLOW_SETTINGS_EVIDENCE_POLICY_KEY in settings:
        validate_flow_evidence_policy_object(
            settings[FLOW_SETTINGS_EVIDENCE_POLICY_KEY]
        )
    if FLOW_SETTINGS_RUNTIME_POLICY_KEY in settings:
        validate_flow_runtime_policy_object(settings[FLOW_SETTINGS_RUNTIME_POLICY_KEY])

    return settings


def _translate_value_error(validate: Callable[[], object]) -> None:
    try:
        validate()
    except ValueError as error:
        raise BadRequestException(
            str(error),
            code="flow_settings_invalid_payload",
        ) from error


def _copy_string_key_mapping(value: Mapping[object, object]) -> dict[str, Any]:
    return {str(key): raw_value for key, raw_value in value.items()}
