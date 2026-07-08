from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final, Mapping, cast

from eneo.authentication.auth_models import (
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_metadata import FlowMetadataParseMode, parse_flow_metadata
from eneo.main.exceptions import BadRequestException

FLOW_EVIDENCE_POLICY_SETTINGS_KEY: Final[str] = "evidence_policy"
FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY: Final[str] = "version"
FLOW_EVIDENCE_POLICY_STORAGE_VERSION: Final[int] = 1
FLOW_EVIDENCE_POLICY_ALLOW_SENSITIVE_KEY: Final[str] = "allow_sensitive_flow_exports"
FLOW_EVIDENCE_POLICY_CLASS3_KEY: Final[str] = "classification_3"
FLOW_EVIDENCE_POLICY_SPACE_ADMIN_RAW_KEY: Final[str] = "allow_space_admin_raw_export"
FLOW_EVIDENCE_POLICY_RUN_OWNER_RAW_KEY: Final[str] = "allow_run_owner_raw_export"
FLOW_EVIDENCE_POLICY_SERVICE_KEY_RAW_KEY: Final[str] = "allow_service_key_raw_export"
FLOW_EVIDENCE_POLICY_TOP_LEVEL_FLAG_KEYS: Final[frozenset[str]] = frozenset(
    {FLOW_EVIDENCE_POLICY_ALLOW_SENSITIVE_KEY}
)
FLOW_EVIDENCE_POLICY_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY,
        FLOW_EVIDENCE_POLICY_ALLOW_SENSITIVE_KEY,
        FLOW_EVIDENCE_POLICY_CLASS3_KEY,
    }
)
FLOW_EVIDENCE_POLICY_CLASS3_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_EVIDENCE_POLICY_SPACE_ADMIN_RAW_KEY,
        FLOW_EVIDENCE_POLICY_RUN_OWNER_RAW_KEY,
        FLOW_EVIDENCE_POLICY_SERVICE_KEY_RAW_KEY,
    }
)


class EvidenceCapabilityLevel(IntEnum):
    NONE = 0
    VIEW = 1
    REDACTED_EXPORT = 2
    RAW_EXPORT = 3


@dataclass(frozen=True)
class FlowEvidencePolicy:
    allow_sensitive_flow_exports: bool = False
    allow_space_admin_raw_export_class3: bool = False
    allow_run_owner_raw_export_class3: bool = False
    allow_service_key_raw_export_class3: bool = False


def resolve_flow_evidence_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> FlowEvidencePolicy:
    evidence_policy = _extract_evidence_policy(tenant_flow_settings)
    class3 = _extract_class3_policy(evidence_policy)

    return FlowEvidencePolicy(
        allow_sensitive_flow_exports=_enabled_flag(
            evidence_policy,
            FLOW_EVIDENCE_POLICY_ALLOW_SENSITIVE_KEY,
        ),
        allow_space_admin_raw_export_class3=_enabled_flag(
            class3,
            FLOW_EVIDENCE_POLICY_SPACE_ADMIN_RAW_KEY,
        ),
        allow_run_owner_raw_export_class3=_enabled_flag(
            class3,
            FLOW_EVIDENCE_POLICY_RUN_OWNER_RAW_KEY,
        ),
        allow_service_key_raw_export_class3=_enabled_flag(
            class3,
            FLOW_EVIDENCE_POLICY_SERVICE_KEY_RAW_KEY,
        ),
    )


def validate_flow_evidence_policy_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BadRequestException(
            "flow_settings.evidence_policy must be an object",
            code="flow_evidence_policy_invalid",
        )

    evidence_policy = cast(dict[str, Any], value)
    _reject_unknown_fields(
        evidence_policy,
        allowed_keys=FLOW_EVIDENCE_POLICY_TOP_LEVEL_KEYS,
        path="flow_settings.evidence_policy",
    )
    _validate_storage_version(
        evidence_policy.get(FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY)
    )
    for key in FLOW_EVIDENCE_POLICY_TOP_LEVEL_FLAG_KEYS:
        if key in evidence_policy:
            _validate_bool_flag(
                evidence_policy[key],
                path=f"flow_settings.evidence_policy.{key}",
            )

    class3 = evidence_policy.get(FLOW_EVIDENCE_POLICY_CLASS3_KEY)
    if class3 is None:
        return evidence_policy
    if not isinstance(class3, dict):
        raise BadRequestException(
            "flow_settings.evidence_policy.classification_3 must be an object",
            code="flow_evidence_policy_invalid",
        )

    class3_dict = cast(dict[str, Any], class3)
    _reject_unknown_fields(
        class3_dict,
        allowed_keys=FLOW_EVIDENCE_POLICY_CLASS3_KEYS,
        path="flow_settings.evidence_policy.classification_3",
    )
    for key in FLOW_EVIDENCE_POLICY_CLASS3_KEYS:
        if key in class3_dict:
            _validate_bool_flag(
                class3_dict[key],
                path=f"flow_settings.evidence_policy.classification_3.{key}",
            )

    return evidence_policy


def apply_flow_evidence_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    allow_sensitive_flow_exports: bool | None = None,
    allow_space_admin_raw_export_class3: bool | None = None,
    allow_run_owner_raw_export_class3: bool | None = None,
    allow_service_key_raw_export_class3: bool | None = None,
) -> dict[str, Any]:
    next_settings = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    existing_policy = _extract_evidence_policy(next_settings)
    evidence_policy = _copy_bool_flags(
        existing_policy,
        FLOW_EVIDENCE_POLICY_TOP_LEVEL_FLAG_KEYS,
    )
    class3 = _copy_bool_flags(
        _extract_class3_policy(existing_policy),
        FLOW_EVIDENCE_POLICY_CLASS3_KEYS,
    )

    updates = {
        FLOW_EVIDENCE_POLICY_ALLOW_SENSITIVE_KEY: allow_sensitive_flow_exports,
        FLOW_EVIDENCE_POLICY_SPACE_ADMIN_RAW_KEY: allow_space_admin_raw_export_class3,
        FLOW_EVIDENCE_POLICY_RUN_OWNER_RAW_KEY: allow_run_owner_raw_export_class3,
        FLOW_EVIDENCE_POLICY_SERVICE_KEY_RAW_KEY: allow_service_key_raw_export_class3,
    }
    for key, value in updates.items():
        if value is not None:
            if key == FLOW_EVIDENCE_POLICY_ALLOW_SENSITIVE_KEY:
                evidence_policy[key] = value
            else:
                class3[key] = value

    evidence_policy[FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY] = (
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION
    )
    evidence_policy[FLOW_EVIDENCE_POLICY_CLASS3_KEY] = class3
    validate_flow_evidence_policy_object(evidence_policy)
    next_settings[FLOW_EVIDENCE_POLICY_SETTINGS_KEY] = evidence_policy
    return next_settings


def _extract_evidence_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}

    evidence_policy = tenant_flow_settings.get(FLOW_EVIDENCE_POLICY_SETTINGS_KEY)
    if not isinstance(evidence_policy, dict):
        return {}
    evidence_policy_dict = cast(dict[str, Any], evidence_policy)
    if not _is_supported_storage_version(
        evidence_policy_dict.get(FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY)
    ):
        return {}
    return dict(evidence_policy_dict)


def _extract_class3_policy(evidence_policy: dict[str, Any]) -> dict[str, Any]:
    class3 = evidence_policy.get(FLOW_EVIDENCE_POLICY_CLASS3_KEY)
    if not isinstance(class3, dict):
        return {}
    return dict(cast(dict[str, Any], class3))


def _enabled_flag(policy: dict[str, Any], key: str) -> bool:
    # Only exact True enables capability; corrupt JSONB strings must fail closed.
    return policy.get(key) is True


def _copy_bool_flags(
    source: dict[str, Any],
    keys: frozenset[str],
) -> dict[str, Any]:
    return {
        key: source[key]
        for key in keys
        if key in source and isinstance(source[key], bool)
    }


def _validate_bool_flag(value: Any, *, path: str) -> None:
    if not isinstance(value, bool):
        raise BadRequestException(
            f"{path} must be a boolean",
            code="flow_evidence_policy_invalid",
        )


def _is_supported_storage_version(value: Any) -> bool:
    # `bool` is an `int` subclass, so use exact type equality for storage versions.
    return value is None or (
        type(value) is int and value == FLOW_EVIDENCE_POLICY_STORAGE_VERSION
    )


def _validate_storage_version(value: Any) -> None:
    if _is_supported_storage_version(value):
        return
    raise BadRequestException(
        "flow_settings.evidence_policy.version must be 1",
        code="flow_evidence_policy_invalid",
    )


def _reject_unknown_fields(
    value: dict[str, Any],
    *,
    allowed_keys: frozenset[str],
    path: str,
) -> None:
    unknown_fields = set(value) - allowed_keys
    if not unknown_fields:
        return
    unknown = ", ".join(sorted(unknown_fields))
    raise BadRequestException(
        f"{path} contains unknown fields: {unknown}",
        code="flow_evidence_policy_unknown_field",
    )


def flow_metadata_marks_sensitive(
    metadata_json: FlowPersistedJsonObject | Mapping[str, object] | None,
) -> bool:
    return parse_flow_metadata(
        metadata_json,
        mode=FlowMetadataParseMode.PERSISTED_READ,
    ).care_data_policy.sensitive


def resolve_service_key_evidence_capability(
    resource_permissions: ResourcePermissions | None,
) -> EvidenceCapabilityLevel:
    """Map service-key evidence permissions to Flow evidence capability."""
    if resource_permissions is None:
        return EvidenceCapabilityLevel.NONE

    level = resource_permissions.flow_evidence
    if level is ResourcePermissionLevel.ADMIN:
        return EvidenceCapabilityLevel.RAW_EXPORT
    if level is ResourcePermissionLevel.WRITE:
        return EvidenceCapabilityLevel.REDACTED_EXPORT
    if level is ResourcePermissionLevel.READ:
        return EvidenceCapabilityLevel.VIEW
    return EvidenceCapabilityLevel.NONE


def classification_level_for_space(space: Any) -> int:
    classification = getattr(space, "security_classification", None)
    level = getattr(classification, "security_level", None)
    return level if isinstance(level, int) else 0
