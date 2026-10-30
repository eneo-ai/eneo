from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final, cast

from eneo.flows.domain.flow_authoring_chat_policy import (
    FLOW_AUTHORING_CHAT_SETTINGS_KEY,
    validate_flow_authoring_chat_policy_object,
)
from eneo.flows.domain.mapped_execution_policy import (
    validate_flow_mapped_execution_policy_object,
)
from eneo.flows.domain.rag_evidence_policy import (
    validate_flow_rag_evidence_policy_object,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_document_limits import (
    validate_flow_document_render_limits_object,
)
from eneo.flows.flow_evidence_policy import (
    RETIRED_FLOW_EVIDENCE_POLICY_KEYS,
    validate_flow_evidence_policy_object,
)
from eneo.flows.flow_input_limits import (
    RETIRED_FLOW_SIZE_KEYS,
    validate_flow_input_limits_object,
)
from eneo.flows.flow_retention_policy import (
    normalize_flow_retention_policy_settings,
    validate_flow_retention_policy_object,
)
from eneo.flows.flow_runtime_policy import validate_flow_runtime_policy_object
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

FLOW_SETTINGS_INPUT_LIMITS_KEY: Final[str] = "input_limits"
FLOW_SETTINGS_DOCUMENT_RENDER_LIMITS_KEY: Final[str] = "document_render_limits"
FLOW_SETTINGS_RUNTIME_POLICY_KEY: Final[str] = "runtime_policy"
FLOW_SETTINGS_EVIDENCE_POLICY_KEY: Final[str] = "evidence_policy"
FLOW_SETTINGS_RETENTION_POLICY_KEY: Final[str] = "retention_policy"
FLOW_SETTINGS_MAPPED_EXECUTION_KEY: Final[str] = "mapped_execution"
FLOW_SETTINGS_RAG_EVIDENCE_KEY: Final[str] = "rag_evidence"
FLOW_SETTINGS_AUTHORING_CHAT_KEY: Final[str] = FLOW_AUTHORING_CHAT_SETTINGS_KEY

FLOW_SETTINGS_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_SETTINGS_INPUT_LIMITS_KEY,
        FLOW_SETTINGS_DOCUMENT_RENDER_LIMITS_KEY,
        FLOW_SETTINGS_RUNTIME_POLICY_KEY,
        FLOW_SETTINGS_EVIDENCE_POLICY_KEY,
        FLOW_SETTINGS_RETENTION_POLICY_KEY,
        FLOW_SETTINGS_MAPPED_EXECUTION_KEY,
        FLOW_SETTINGS_RAG_EVIDENCE_KEY,
        FLOW_SETTINGS_AUTHORING_CHAT_KEY,
    }
)

# Settings that moved to another owner. Stored rows may still carry them: they
# are dropped when a row is read and refused when settings are written.
_RETIRED_KEYS_BY_SECTION: Final[tuple[tuple[str, frozenset[str]], ...]] = (
    (FLOW_SETTINGS_INPUT_LIMITS_KEY, RETIRED_FLOW_SIZE_KEYS),
    (FLOW_SETTINGS_EVIDENCE_POLICY_KEY, RETIRED_FLOW_EVIDENCE_POLICY_KEYS),
)

# Sections whose owner is gone. Stored rows may still carry them: they are
# dropped when a row is read and refused, as unknown, when settings are written.
_RETIRED_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"ai_builder"})

# Bounded by distinct unknown key names, not tenants, to avoid log spam from
# historical JSONB rows without hiding newly observed keys.
_warned_unknown_top_level_keys: set[str] = set()


def normalize_flow_settings_object(value: object | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}

    settings = _copy_string_key_mapping(cast(Mapping[object, object], value))
    unknown_fields = (
        set(settings) - FLOW_SETTINGS_TOP_LEVEL_KEYS - _RETIRED_TOP_LEVEL_KEYS
    )
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
    for section_key, retired_keys in _RETIRED_KEYS_BY_SECTION:
        section = known_settings.get(section_key)
        if isinstance(section, dict):
            known_settings[section_key] = {
                key: value
                for key, value in _copy_string_key_mapping(
                    cast(Mapping[object, object], section)
                ).items()
                if key not in retired_keys
            }
    return normalize_flow_retention_policy_settings(known_settings)


def validate_flow_settings_write(value: object | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise FlowBadRequestException(
            "flow_settings must be an object.",
            code=FlowApiErrorCode.SETTINGS_INVALID_PAYLOAD,
        )

    settings = _copy_string_key_mapping(cast(Mapping[object, object], value))
    unknown_fields = set(settings) - FLOW_SETTINGS_TOP_LEVEL_KEYS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise BadRequestException(
            f"flow_settings contains unknown top-level fields: {unknown}",
        )

    input_limits = settings.get(FLOW_SETTINGS_INPUT_LIMITS_KEY)
    if isinstance(input_limits, Mapping) and RETIRED_FLOW_SIZE_KEYS.intersection(
        cast(Mapping[object, object], input_limits)
    ):
        raise FlowBadRequestException(
            "File and audio sizes are managed in Admin > File storage, for all flows.",
            code=FlowApiErrorCode.SETTINGS_INVALID_PAYLOAD,
        )
    evidence_policy = settings.get(FLOW_SETTINGS_EVIDENCE_POLICY_KEY)
    if isinstance(
        evidence_policy, Mapping
    ) and RETIRED_FLOW_EVIDENCE_POLICY_KEYS.intersection(
        cast(Mapping[object, object], evidence_policy)
    ):
        raise FlowBadRequestException(
            "Evidence export is each flow's own setting "
            "(metadata_json.evidence_policy.allow_export).",
            code=FlowApiErrorCode.SETTINGS_INVALID_PAYLOAD,
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
    if FLOW_SETTINGS_MAPPED_EXECUTION_KEY in settings:
        validate_flow_mapped_execution_policy_object(
            settings[FLOW_SETTINGS_MAPPED_EXECUTION_KEY]
        )
    if FLOW_SETTINGS_RAG_EVIDENCE_KEY in settings:
        validate_flow_rag_evidence_policy_object(
            settings[FLOW_SETTINGS_RAG_EVIDENCE_KEY]
        )
    if FLOW_SETTINGS_AUTHORING_CHAT_KEY in settings:
        validate_flow_authoring_chat_policy_object(
            settings[FLOW_SETTINGS_AUTHORING_CHAT_KEY]
        )

    return settings


def _translate_value_error(validate: Callable[[], object]) -> None:
    try:
        validate()
    except ValueError as error:
        raise FlowBadRequestException(
            str(error),
            code=FlowApiErrorCode.SETTINGS_INVALID_PAYLOAD,
        ) from error


def _copy_string_key_mapping(value: Mapping[object, object]) -> dict[str, Any]:
    return {str(key): raw_value for key, raw_value in value.items()}
