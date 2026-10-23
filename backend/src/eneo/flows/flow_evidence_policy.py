from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final, Mapping, cast
from uuid import UUID

from eneo.authentication.auth_models import (
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_metadata import FlowMetadataParseMode, parse_flow_metadata
from eneo.main.exceptions import BadRequestException

# Evidence held to this level or above withholds verbatim passage text below a
# raw export, and its raw export follows the tenant's classification-3 policy.
# Owned here with the rest of the sensitivity vocabulary.
CLASSIFIED_SECURITY_LEVEL: Final[int] = 3

FLOW_EVIDENCE_POLICY_SETTINGS_KEY: Final[str] = "evidence_policy"
FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY: Final[str] = "version"
FLOW_EVIDENCE_POLICY_STORAGE_VERSION: Final[int] = 1
FLOW_EVIDENCE_POLICY_CLASS3_KEY: Final[str] = "classification_3"
FLOW_EVIDENCE_POLICY_SPACE_ADMIN_RAW_KEY: Final[str] = "allow_space_admin_raw_export"
FLOW_EVIDENCE_POLICY_RUN_OWNER_RAW_KEY: Final[str] = "allow_run_owner_raw_export"
FLOW_EVIDENCE_POLICY_SERVICE_KEY_RAW_KEY: Final[str] = "allow_service_key_raw_export"
FLOW_EVIDENCE_POLICY_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY,
        FLOW_EVIDENCE_POLICY_CLASS3_KEY,
    }
)
# Export of a sensitive flow's evidence was a tenant switch before each flow
# got its own (`metadata_json.evidence_policy.allow_export`). Stored rows may
# still carry the key; it is dropped when read and refused when written.
RETIRED_FLOW_EVIDENCE_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {"allow_sensitive_flow_exports"}
)
FLOW_EVIDENCE_POLICY_CLASS3_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_EVIDENCE_POLICY_SPACE_ADMIN_RAW_KEY,
        FLOW_EVIDENCE_POLICY_RUN_OWNER_RAW_KEY,
        FLOW_EVIDENCE_POLICY_SERVICE_KEY_RAW_KEY,
    }
)


@dataclass(frozen=True, slots=True)
class FlowHistoryAccessContext:
    """The facts that authorize reading a flow's runs, live or retired.

    Read as one narrow row rather than through the full Flow aggregate: the
    decisions need the space, publication, sensitivity and the space's current
    classification, not the flow's steps, and must not depend on a space read
    that enforces membership. A retired (deleted) flow keeps this row, so its
    history stays readable with current authorization and follows its retention rule.
    """

    flow_id: UUID
    space_id: UUID
    published: bool
    retired: bool
    sensitive: bool
    evidence_export_allowed: bool
    classification_level: int

    @property
    def id(self) -> UUID:
        return self.flow_id


class EvidenceCapabilityLevel(IntEnum):
    NONE = 0
    VIEW = 1
    REDACTED_EXPORT = 2
    RAW_EXPORT = 3


@dataclass(frozen=True)
class FlowEvidencePolicy:
    allow_space_admin_raw_export_class3: bool = False
    allow_run_owner_raw_export_class3: bool = False
    allow_service_key_raw_export_class3: bool = False


def resolve_flow_evidence_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> FlowEvidencePolicy:
    evidence_policy = _extract_evidence_policy(tenant_flow_settings)
    class3 = _extract_class3_policy(evidence_policy)

    return FlowEvidencePolicy(
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
    class3 = evidence_policy.get(FLOW_EVIDENCE_POLICY_CLASS3_KEY)
    if class3 is None:
        return evidence_policy
    if not isinstance(class3, dict):
        raise BadRequestException(
            "flow_settings.evidence_policy.classification_3 must be an object",
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
    allow_space_admin_raw_export_class3: bool | None = None,
    allow_run_owner_raw_export_class3: bool | None = None,
    allow_service_key_raw_export_class3: bool | None = None,
) -> dict[str, Any]:
    next_settings = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    class3 = _copy_bool_flags(
        _extract_class3_policy(_extract_evidence_policy(next_settings)),
        FLOW_EVIDENCE_POLICY_CLASS3_KEYS,
    )

    updates = {
        FLOW_EVIDENCE_POLICY_SPACE_ADMIN_RAW_KEY: allow_space_admin_raw_export_class3,
        FLOW_EVIDENCE_POLICY_RUN_OWNER_RAW_KEY: allow_run_owner_raw_export_class3,
        FLOW_EVIDENCE_POLICY_SERVICE_KEY_RAW_KEY: allow_service_key_raw_export_class3,
    }
    for key, value in updates.items():
        if value is not None:
            class3[key] = value

    evidence_policy: dict[str, Any] = {
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY: FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
        FLOW_EVIDENCE_POLICY_CLASS3_KEY: class3,
    }
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
    )


@dataclass(frozen=True, slots=True)
class FlowEvidenceMetadataFacts:
    """What a flow's own metadata says about its evidence."""

    sensitive: bool
    export_allowed: bool


def flow_evidence_metadata_facts(
    metadata_json: FlowPersistedJsonObject | Mapping[str, object] | None,
) -> FlowEvidenceMetadataFacts:
    """The flow's evidence facts for an access decision, failing closed when unreadable.

    Persisted metadata that cannot be parsed cannot be shown to be
    non-sensitive or to allow export, so it withholds content and refuses the
    export. Raising instead would make the evidence view unreachable for the
    flow, which hides the whole trace rather than the part that needs protecting.
    """
    try:
        metadata = parse_flow_metadata(
            metadata_json,
            mode=FlowMetadataParseMode.PERSISTED_READ,
        )
    except BadRequestException:
        return FlowEvidenceMetadataFacts(sensitive=True, export_allowed=False)
    return FlowEvidenceMetadataFacts(
        sensitive=metadata.care_data_policy.sensitive,
        export_allowed=metadata.evidence_policy.allow_export,
    )


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
