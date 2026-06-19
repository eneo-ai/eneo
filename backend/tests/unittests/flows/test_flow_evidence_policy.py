from __future__ import annotations

import pytest

from intric.authentication.auth_models import (
    ResourcePermissionLevel,
    ResourcePermissions,
)
from intric.flows.flow_evidence_policy import (
    FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
    FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY,
    EvidenceCapabilityLevel,
    FlowEvidencePolicy,
    apply_flow_evidence_policy_patch,
    resolve_flow_evidence_policy,
    resolve_service_key_evidence_capability,
    validate_flow_evidence_policy_object,
)
from intric.main.exceptions import BadRequestException


@pytest.mark.parametrize(
    "corrupt_value",
    ("yes", "true", "1", 1, [True], {"enabled": True}),
)
def test_resolve_flow_evidence_policy_uses_only_exact_boolean_flags(
    corrupt_value: object,
) -> None:
    policy = resolve_flow_evidence_policy(
        {
            "evidence_policy": {
                "allow_sensitive_flow_exports": corrupt_value,
                "classification_3": {
                    "allow_space_admin_raw_export": corrupt_value,
                    "allow_run_owner_raw_export": True,
                    "allow_service_key_raw_export": corrupt_value,
                },
            }
        }
    )

    assert policy == FlowEvidencePolicy(allow_run_owner_raw_export_class3=True)


def test_resolve_flow_evidence_policy_handles_corrupt_policy_shape() -> None:
    assert resolve_flow_evidence_policy({"evidence_policy": "broken"}) == (
        FlowEvidencePolicy()
    )


def test_resolve_flow_evidence_policy_treats_missing_storage_version_as_v1() -> None:
    assert resolve_flow_evidence_policy(
        {"evidence_policy": {"allow_sensitive_flow_exports": True}}
    ) == FlowEvidencePolicy(allow_sensitive_flow_exports=True)


def test_resolve_flow_evidence_policy_fails_closed_for_unknown_storage_version() -> None:
    assert resolve_flow_evidence_policy(
        {
            "evidence_policy": {
                "version": 99,
                "allow_sensitive_flow_exports": True,
            }
        }
    ) == FlowEvidencePolicy()


@pytest.mark.parametrize(
    ("level", "expected"),
    (
        (None, EvidenceCapabilityLevel.NONE),
        (ResourcePermissionLevel.NONE, EvidenceCapabilityLevel.NONE),
        (ResourcePermissionLevel.READ, EvidenceCapabilityLevel.VIEW),
        (ResourcePermissionLevel.WRITE, EvidenceCapabilityLevel.REDACTED_EXPORT),
        (ResourcePermissionLevel.ADMIN, EvidenceCapabilityLevel.RAW_EXPORT),
    ),
)
def test_resolve_service_key_evidence_capability_maps_typed_resource_permissions(
    level: ResourcePermissionLevel | None,
    expected: EvidenceCapabilityLevel,
) -> None:
    resource_permissions = (
        None if level is None else ResourcePermissions(flow_evidence=level)
    )

    assert resolve_service_key_evidence_capability(resource_permissions) == expected


def test_validate_flow_evidence_policy_object_accepts_public_shape() -> None:
    policy = {
        "version": FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
        "allow_sensitive_flow_exports": True,
        "classification_3": {
            "allow_space_admin_raw_export": True,
            "allow_run_owner_raw_export": False,
            "allow_service_key_raw_export": True,
        },
    }

    assert validate_flow_evidence_policy_object(policy) == policy
    assert validate_flow_evidence_policy_object(None) == {}
    assert validate_flow_evidence_policy_object(
        {"allow_sensitive_flow_exports": True}
    ) == {"allow_sensitive_flow_exports": True}


@pytest.mark.parametrize("version", (0, 2, "1", True))
def test_validate_flow_evidence_policy_object_rejects_unknown_storage_version(
    version: object,
) -> None:
    with pytest.raises(
        BadRequestException,
        match="flow_settings.evidence_policy.version",
    ):
        validate_flow_evidence_policy_object({"version": version})


def test_validate_flow_evidence_policy_object_rejects_non_bool_sensitive_flag() -> None:
    with pytest.raises(
        BadRequestException,
        match="flow_settings.evidence_policy.allow_sensitive_flow_exports",
    ):
        validate_flow_evidence_policy_object({"allow_sensitive_flow_exports": "yes"})


@pytest.mark.parametrize(
    ("policy", "message"),
    (
        (
            {"unknown": True},
            "flow_settings.evidence_policy contains unknown fields: unknown",
        ),
        (
            {"classification_3": {"unknown": True}},
            "flow_settings.evidence_policy.classification_3 contains unknown fields: unknown",
        ),
    ),
)
def test_validate_flow_evidence_policy_object_rejects_unknown_fields(
    policy: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BadRequestException, match=message):
        validate_flow_evidence_policy_object(policy)


def test_apply_flow_evidence_policy_patch_handles_corrupt_policy() -> None:
    updated = apply_flow_evidence_policy_patch(
        {"evidence_policy": "broken"},
        allow_sensitive_flow_exports=True,
        allow_service_key_raw_export_class3=True,
    )

    assert updated["evidence_policy"] == {
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY: FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
        "allow_sensitive_flow_exports": True,
        "classification_3": {"allow_service_key_raw_export": True},
    }


def test_apply_flow_evidence_policy_patch_preserves_unrelated_settings() -> None:
    current_settings = {
        "input_limits": {"max_files_per_run": 10},
        "retention_policy": {"run_debug_evidence_days": 7},
        "ai_builder": {"minimum_conversation_budget_tokens": 6000},
        "runtime_policy": {"default_step_timeout_seconds": 900},
        "document_render_limits": {"max_source_chars": 500_000},
        "evidence_policy": {"classification_3": "broken"},
    }

    updated = apply_flow_evidence_policy_patch(
        current_settings,
        allow_run_owner_raw_export_class3=True,
    )

    for key in (
        "input_limits",
        "retention_policy",
        "ai_builder",
        "runtime_policy",
        "document_render_limits",
    ):
            assert updated[key] == current_settings[key]
    assert updated["evidence_policy"] == {
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY: FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
        "classification_3": {"allow_run_owner_raw_export": True}
    }
