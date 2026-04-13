from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, cast

from intric.authentication.auth_models import (
    ResourcePermissionLevel,
    ResourcePermissions,
)


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
    if not isinstance(tenant_flow_settings, dict):
        return FlowEvidencePolicy()

    evidence_policy = tenant_flow_settings.get("evidence_policy")
    if not isinstance(evidence_policy, dict):
        return FlowEvidencePolicy()
    evidence_policy_dict = cast(dict[str, Any], evidence_policy)

    class3 = evidence_policy_dict.get("classification_3")
    if not isinstance(class3, dict):
        return FlowEvidencePolicy()
    class3_dict = cast(dict[str, Any], class3)

    return FlowEvidencePolicy(
        allow_space_admin_raw_export_class3=bool(
            class3_dict.get("allow_space_admin_raw_export", False)
        ),
        allow_run_owner_raw_export_class3=bool(
            class3_dict.get("allow_run_owner_raw_export", False)
        ),
        allow_service_key_raw_export_class3=bool(
            class3_dict.get("allow_service_key_raw_export", False)
        ),
    )


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
    evidence_policy = dict(next_settings.get("evidence_policy", {}))
    class3 = dict(evidence_policy.get("classification_3", {}))

    updates = {
        "allow_space_admin_raw_export": allow_space_admin_raw_export_class3,
        "allow_run_owner_raw_export": allow_run_owner_raw_export_class3,
        "allow_service_key_raw_export": allow_service_key_raw_export_class3,
    }
    for key, value in updates.items():
        if value is not None:
            class3[key] = value

    evidence_policy["classification_3"] = class3
    next_settings["evidence_policy"] = evidence_policy
    return next_settings


def resolve_service_key_evidence_capability(user: Any) -> EvidenceCapabilityLevel:
    key = getattr(user, "active_api_key", None)
    if key is None:
        return EvidenceCapabilityLevel.NONE
    resource_permissions = getattr(key, "resource_permissions", None)
    if resource_permissions is None:
        return EvidenceCapabilityLevel.NONE

    if isinstance(resource_permissions, dict):
        try:
            resource_permissions = ResourcePermissions.model_validate(
                resource_permissions
            )
        except Exception:
            return EvidenceCapabilityLevel.NONE

    level = getattr(resource_permissions, "flow_evidence", ResourcePermissionLevel.NONE)
    level_value = getattr(level, "value", str(level))
    if level_value == ResourcePermissionLevel.ADMIN.value:
        return EvidenceCapabilityLevel.RAW_EXPORT
    if level_value == ResourcePermissionLevel.WRITE.value:
        return EvidenceCapabilityLevel.REDACTED_EXPORT
    if level_value == ResourcePermissionLevel.READ.value:
        return EvidenceCapabilityLevel.VIEW
    return EvidenceCapabilityLevel.NONE


def classification_level_for_space(space: Any) -> int:
    classification = getattr(space, "security_classification", None)
    level = getattr(classification, "security_level", None)
    return level if isinstance(level, int) else 0
