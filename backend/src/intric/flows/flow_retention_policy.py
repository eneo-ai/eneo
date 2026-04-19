from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

RetentionDataClass = Literal[
    "source_audio",
    "transcript_text",
    "generated_artifact",
    "run_debug_evidence",
]

RETENTION_POLICY_FIELDS = {
    "shared_default_days",
    "source_audio_days",
    "transcript_text_days",
    "generated_artifact_days",
    "run_debug_evidence_days",
}


@dataclass(frozen=True)
class FlowRetentionPolicy:
    shared_default_days: int | None = None
    source_audio_days: int | None = None
    transcript_text_days: int | None = None
    generated_artifact_days: int | None = None
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
        class_specific = {
            "source_audio": self.source_audio_days,
            "transcript_text": self.transcript_text_days,
            "generated_artifact": self.generated_artifact_days,
            "run_debug_evidence": self.run_debug_evidence_days,
        }[data_class]
        if class_specific is not None:
            return class_specific
        if space_default_days is not None:
            return space_default_days
        return self.shared_default_days


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
        shared_default_days=_int_or_none(
            retention_policy_dict.get("shared_default_days")
        ),
        source_audio_days=_int_or_none(retention_policy_dict.get("source_audio_days")),
        transcript_text_days=_int_or_none(
            retention_policy_dict.get("transcript_text_days")
        ),
        generated_artifact_days=_int_or_none(
            retention_policy_dict.get("generated_artifact_days")
        ),
        run_debug_evidence_days=_int_or_none(
            retention_policy_dict.get("run_debug_evidence_days")
        ),
    )


def apply_flow_retention_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    shared_default_days: int | None = None,
    source_audio_days: int | None = None,
    transcript_text_days: int | None = None,
    generated_artifact_days: int | None = None,
    run_debug_evidence_days: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    next_settings = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    retention_policy = dict(next_settings.get("retention_policy", {}))
    updates = {
        "shared_default_days": shared_default_days,
        "source_audio_days": source_audio_days,
        "transcript_text_days": transcript_text_days,
        "generated_artifact_days": generated_artifact_days,
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
