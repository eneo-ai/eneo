from __future__ import annotations

import pytest

from eneo.authentication.auth_models import (
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.flows.flow_evidence_policy import (
    FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
    FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY,
    EvidenceCapabilityLevel,
    FlowEvidenceMetadataFacts,
    FlowEvidencePolicy,
    apply_flow_evidence_policy_patch,
    flow_evidence_metadata_facts,
    resolve_flow_evidence_policy,
    resolve_service_key_evidence_capability,
    validate_flow_evidence_policy_object,
)
from eneo.main.exceptions import BadRequestException


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
        {"evidence_policy": {"classification_3": {"allow_run_owner_raw_export": True}}}
    ) == FlowEvidencePolicy(allow_run_owner_raw_export_class3=True)


def test_resolve_flow_evidence_policy_fails_closed_for_unknown_storage_version() -> (
    None
):
    assert (
        resolve_flow_evidence_policy(
            {
                "evidence_policy": {
                    "version": 99,
                    "classification_3": {"allow_run_owner_raw_export": True},
                }
            }
        )
        == FlowEvidencePolicy()
    )


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
        "classification_3": {
            "allow_space_admin_raw_export": True,
            "allow_run_owner_raw_export": False,
            "allow_service_key_raw_export": True,
        },
    }

    assert validate_flow_evidence_policy_object(policy) == policy
    assert validate_flow_evidence_policy_object(None) == {}


@pytest.mark.parametrize("version", (0, 2, "1", True))
def test_validate_flow_evidence_policy_object_rejects_unknown_storage_version(
    version: object,
) -> None:
    with pytest.raises(
        BadRequestException,
        match="flow_settings.evidence_policy.version",
    ):
        validate_flow_evidence_policy_object({"version": version})


@pytest.mark.parametrize(
    ("policy", "message"),
    (
        (
            {"unknown": True},
            "flow_settings.evidence_policy contains unknown fields: unknown",
        ),
        (
            # Export is each flow's own setting now; the tenant switch is gone.
            {"allow_sensitive_flow_exports": True},
            "flow_settings.evidence_policy contains unknown fields: "
            "allow_sensitive_flow_exports",
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
        allow_service_key_raw_export_class3=True,
    )

    assert updated["evidence_policy"] == {
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY: FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
        "classification_3": {"allow_service_key_raw_export": True},
    }


def test_apply_flow_evidence_policy_patch_preserves_unrelated_settings() -> None:
    current_settings = {
        "input_limits": {"max_files_per_run": 10},
        "retention_policy": {"run_debug_evidence_days": 7},
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
        "runtime_policy",
        "document_render_limits",
    ):
        assert updated[key] == current_settings[key]
    assert updated["evidence_policy"] == {
        FLOW_EVIDENCE_POLICY_STORAGE_VERSION_KEY: FLOW_EVIDENCE_POLICY_STORAGE_VERSION,
        "classification_3": {"allow_run_owner_raw_export": True},
    }


def test_unreadable_flow_metadata_is_sensitive_and_cannot_be_exported() -> None:
    """Metadata we cannot parse cannot be shown to be non-sensitive or exportable."""
    unreadable = {
        "form_schema": {"fields": [{"name": "case_id", "type": "nope"}]},
        "evidence_policy": {"allow_export": True},
    }

    assert flow_evidence_metadata_facts(unreadable) == FlowEvidenceMetadataFacts(
        sensitive=True, export_allowed=False
    )


@pytest.mark.parametrize(
    ("metadata_json", "expected"),
    [
        (None, FlowEvidenceMetadataFacts(sensitive=False, export_allowed=False)),
        ({}, FlowEvidenceMetadataFacts(sensitive=False, export_allowed=False)),
        (
            {"care_data_policy": {"sensitive": True}},
            FlowEvidenceMetadataFacts(sensitive=True, export_allowed=False),
        ),
        (
            {"evidence_policy": {"allow_export": True}},
            FlowEvidenceMetadataFacts(sensitive=False, export_allowed=True),
        ),
        (
            {
                "care_data_policy": {"sensitive": True},
                "evidence_policy": {"allow_export": True},
            },
            FlowEvidenceMetadataFacts(sensitive=True, export_allowed=True),
        ),
        (
            {"evidence_policy": {"allow_export": "true"}},
            FlowEvidenceMetadataFacts(sensitive=False, export_allowed=False),
        ),
    ],
)
def test_readable_flow_metadata_keeps_what_it_declares(
    metadata_json: dict[str, object] | None,
    expected: FlowEvidenceMetadataFacts,
) -> None:
    assert flow_evidence_metadata_facts(metadata_json) == expected
