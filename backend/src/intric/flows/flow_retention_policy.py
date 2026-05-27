from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

RetentionDataClass = Literal["run_debug_evidence"]

RETENTION_POLICY_FIELDS = {
    "run_debug_evidence_days",
}


@dataclass(frozen=True)
class FlowRetentionPolicy:
    run_debug_evidence_days: int | None = None

    def retention_for_class(
        self,
        data_class: RetentionDataClass,
        *,
        space_default_days: int | None = None,
        flow_override_days: int | None = None,
    ) -> int | None:
        if flow_override_days is not None:
            return flow_override_days
        if (
            data_class == "run_debug_evidence"
            and self.run_debug_evidence_days is not None
        ):
            return self.run_debug_evidence_days
        return space_default_days


def resolve_flow_retention_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> FlowRetentionPolicy:
    if not isinstance(tenant_flow_settings, dict):
        return FlowRetentionPolicy()

    retention_policy = tenant_flow_settings.get("retention_policy")
    if not isinstance(retention_policy, dict):
        return FlowRetentionPolicy()
    retention_policy_dict = cast(dict[str, Any], retention_policy)

    return FlowRetentionPolicy(
        run_debug_evidence_days=_int_or_none(
            retention_policy_dict.get("run_debug_evidence_days")
        ),
    )


def normalize_flow_retention_policy_settings(
    current_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    next_settings = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    retention_policy = next_settings.get("retention_policy")
    if retention_policy is None:
        return next_settings
    if not isinstance(retention_policy, dict):
        return next_settings

    retention_policy_dict = cast(dict[str, Any], retention_policy)
    next_retention_policy: dict[str, Any] = {}
    if "run_debug_evidence_days" in retention_policy_dict:
        next_retention_policy["run_debug_evidence_days"] = retention_policy_dict[
            "run_debug_evidence_days"
        ]

    if next_retention_policy:
        next_settings["retention_policy"] = next_retention_policy
    else:
        next_settings.pop("retention_policy", None)
    return next_settings


def apply_flow_retention_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    run_debug_evidence_days: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    next_settings = normalize_flow_retention_policy_settings(current_flow_settings)
    existing_retention_policy = next_settings.get("retention_policy")
    retention_policy: dict[str, Any] = (
        dict(cast(dict[str, Any], existing_retention_policy))
        if isinstance(existing_retention_policy, dict)
        else {}
    )
    updates = {
        "run_debug_evidence_days": run_debug_evidence_days,
    }
    for key, value in updates.items():
        if value is not None:
            retention_policy[key] = value
    for key in remove_keys or ():
        if key in RETENTION_POLICY_FIELDS:
            retention_policy.pop(key, None)
    if retention_policy:
        next_settings["retention_policy"] = retention_policy
    else:
        next_settings.pop("retention_policy", None)
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

    for key, raw_value in value_dict.items():
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


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
