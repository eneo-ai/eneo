from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

FLOW_RETENTION_POLICY_SETTINGS_KEY: Final[str] = "retention_policy"
FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY: Final[str] = "version"
FLOW_RETENTION_POLICY_STORAGE_VERSION: Final[int] = 1
FLOW_RETENTION_POLICY_RUN_DEBUG_EVIDENCE_DAYS_KEY: Final[str] = (
    "run_debug_evidence_days"
)
RETENTION_POLICY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY,
        FLOW_RETENTION_POLICY_RUN_DEBUG_EVIDENCE_DAYS_KEY,
    }
)
RETENTION_POLICY_BUSINESS_FIELDS: Final[frozenset[str]] = frozenset(
    {FLOW_RETENTION_POLICY_RUN_DEBUG_EVIDENCE_DAYS_KEY}
)
DELETED_RETENTION_POLICY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "source_audio_days",
        "generated_artifact_days",
    }
)


@dataclass(frozen=True)
class FlowRetentionPolicy:
    run_debug_evidence_days: int | None = None

    def debug_evidence_days(self) -> int | None:
        return self.run_debug_evidence_days


def resolve_flow_retention_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> FlowRetentionPolicy:
    retention_policy_dict = _extract_retention_policy(tenant_flow_settings)
    return FlowRetentionPolicy(
        run_debug_evidence_days=_int_or_none(
            retention_policy_dict.get(FLOW_RETENTION_POLICY_RUN_DEBUG_EVIDENCE_DAYS_KEY)
        ),
    )


def _extract_retention_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}

    retention_policy = tenant_flow_settings.get(FLOW_RETENTION_POLICY_SETTINGS_KEY)
    if not isinstance(retention_policy, dict):
        return {}
    retention_policy_dict = cast(dict[str, Any], retention_policy)
    if not _is_supported_storage_version(
        retention_policy_dict.get(FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY)
    ):
        return {}
    return dict(retention_policy_dict)


def normalize_flow_retention_policy_settings(
    current_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    next_settings = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    retention_policy = next_settings.get(FLOW_RETENTION_POLICY_SETTINGS_KEY)
    if retention_policy is None:
        return next_settings
    if not isinstance(retention_policy, dict):
        return next_settings

    retention_policy_dict = cast(dict[str, Any], retention_policy)
    next_retention_policy: dict[str, Any] = {
        key: value
        for key, value in retention_policy_dict.items()
        if key not in DELETED_RETENTION_POLICY_FIELDS
    }

    if _has_retention_policy_payload(next_retention_policy):
        next_settings[FLOW_RETENTION_POLICY_SETTINGS_KEY] = next_retention_policy
    else:
        next_settings.pop(FLOW_RETENTION_POLICY_SETTINGS_KEY, None)
    return next_settings


def apply_flow_retention_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    run_debug_evidence_days: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    next_settings = normalize_flow_retention_policy_settings(current_flow_settings)
    existing_retention_policy = next_settings.get(FLOW_RETENTION_POLICY_SETTINGS_KEY)
    retention_policy: dict[str, Any] = (
        dict(cast(dict[str, Any], existing_retention_policy))
        if isinstance(existing_retention_policy, dict)
        else {}
    )
    updates = {
        FLOW_RETENTION_POLICY_RUN_DEBUG_EVIDENCE_DAYS_KEY: run_debug_evidence_days,
    }
    for key, value in updates.items():
        if value is not None:
            retention_policy[key] = value
    for key in remove_keys or ():
        if key in RETENTION_POLICY_FIELDS:
            retention_policy.pop(key, None)
    if any(key in retention_policy for key in RETENTION_POLICY_BUSINESS_FIELDS):
        retention_policy[FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY] = (
            FLOW_RETENTION_POLICY_STORAGE_VERSION
        )
        validate_flow_retention_policy_object(retention_policy)
        next_settings[FLOW_RETENTION_POLICY_SETTINGS_KEY] = retention_policy
    else:
        next_settings.pop(FLOW_RETENTION_POLICY_SETTINGS_KEY, None)
    return next_settings


def validate_flow_retention_policy_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("flow_settings.retention_policy must be an object")

    value_dict = cast(dict[str, Any], value)
    unknown_fields = set(value_dict) - RETENTION_POLICY_FIELDS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ValueError(
            f"flow_settings.retention_policy contains unknown fields: {unknown}"
        )
    _validate_storage_version(value_dict.get(FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY))

    for key, raw_value in value_dict.items():
        if key == FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY:
            continue
        if raw_value is None:
            continue
        if not isinstance(raw_value, int) or isinstance(raw_value, bool):
            raise ValueError(
                f"flow_settings.retention_policy.{key} must be an integer or null"
            )
        if raw_value < 1:
            raise ValueError(
                f"flow_settings.retention_policy.{key} must be greater than 0"
            )

    return value_dict


def _is_supported_storage_version(value: Any) -> bool:
    return value is None or (
        type(value) is int and value == FLOW_RETENTION_POLICY_STORAGE_VERSION
    )


def _validate_storage_version(value: Any) -> None:
    if _is_supported_storage_version(value):
        return
    raise ValueError("flow_settings.retention_policy.version must be 1")


def _has_retention_policy_payload(retention_policy: dict[str, Any]) -> bool:
    # Unknown keys stay alive so explicit write validation rejects hidden schema drift.
    return any(
        key in RETENTION_POLICY_BUSINESS_FIELDS or key not in RETENTION_POLICY_FIELDS
        for key in retention_policy
    )


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
