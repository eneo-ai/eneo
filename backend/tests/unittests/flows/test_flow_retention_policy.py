import pytest

from intric.flows.flow_retention_policy import (
    FLOW_RETENTION_POLICY_STORAGE_VERSION,
    FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY,
    FlowRetentionPolicy,
    apply_flow_retention_policy_patch,
    normalize_flow_retention_policy_settings,
    resolve_flow_retention_policy,
    validate_flow_retention_policy_object,
)


def test_resolve_flow_retention_policy_reads_debug_evidence_only() -> None:
    policy = resolve_flow_retention_policy(
        {
            "retention_policy": {
                "source_audio_days": 3,
                "generated_artifact_days": 7,
                "run_debug_evidence_days": 14,
            }
        }
    )

    assert policy == FlowRetentionPolicy(run_debug_evidence_days=14)


def test_resolve_flow_retention_policy_treats_missing_version_as_v1() -> None:
    policy = resolve_flow_retention_policy(
        {"retention_policy": {"run_debug_evidence_days": 14}}
    )

    assert policy == FlowRetentionPolicy(run_debug_evidence_days=14)


@pytest.mark.parametrize("version", [2, True, "1"])
def test_resolve_flow_retention_policy_fails_closed_for_unsupported_version(
    version,
) -> None:
    policy = resolve_flow_retention_policy(
        {"retention_policy": {"version": version, "run_debug_evidence_days": 14}}
    )

    assert policy == FlowRetentionPolicy()


def test_flow_retention_policy_reads_tenant_debug_evidence_only() -> None:
    policy = FlowRetentionPolicy(run_debug_evidence_days=7)

    assert policy.debug_evidence_days() == 7
    assert FlowRetentionPolicy().debug_evidence_days() is None


def test_apply_flow_retention_policy_patch_strips_stale_deleted_keys() -> None:
    updated = apply_flow_retention_policy_patch(
        {
            "retention_policy": {
                "source_audio_days": 3,
                "generated_artifact_days": 7,
                "run_debug_evidence_days": 14,
            }
        },
        run_debug_evidence_days=30,
    )

    assert updated["retention_policy"] == {
        "run_debug_evidence_days": 30,
        FLOW_RETENTION_POLICY_STORAGE_VERSION_KEY: FLOW_RETENTION_POLICY_STORAGE_VERSION,
    }


def test_apply_flow_retention_policy_patch_can_remove_debug_evidence_override() -> None:
    updated = apply_flow_retention_policy_patch(
        {"retention_policy": {"run_debug_evidence_days": 14}},
        run_debug_evidence_days=None,
        remove_keys={"run_debug_evidence_days"},
    )

    assert "retention_policy" not in updated


def test_apply_flow_retention_policy_patch_drops_version_when_policy_is_empty() -> None:
    updated = apply_flow_retention_policy_patch(
        {
            "retention_policy": {
                "version": 1,
                "run_debug_evidence_days": 14,
            }
        },
        run_debug_evidence_days=None,
        remove_keys={"run_debug_evidence_days"},
    )

    assert "retention_policy" not in updated


def test_apply_flow_retention_policy_patch_rejects_stored_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown fields: unexpected_days"):
        apply_flow_retention_policy_patch(
            {"retention_policy": {"unexpected_days": 7}},
            run_debug_evidence_days=30,
        )


def test_normalize_flow_retention_policy_settings_strips_deleted_keys() -> None:
    updated = normalize_flow_retention_policy_settings(
        {
            "runtime_policy": {"default_step_timeout_seconds": 600},
            "retention_policy": {
                "source_audio_days": 3,
                "run_debug_evidence_days": 14,
            },
        }
    )

    assert updated == {
        "runtime_policy": {"default_step_timeout_seconds": 600},
        "retention_policy": {"run_debug_evidence_days": 14},
    }


def test_normalize_flow_retention_policy_settings_drops_version_only_policy() -> None:
    updated = normalize_flow_retention_policy_settings(
        {
            "runtime_policy": {"default_step_timeout_seconds": 600},
            "retention_policy": {
                "version": 1,
                "source_audio_days": 3,
            },
        }
    )

    assert updated == {"runtime_policy": {"default_step_timeout_seconds": 600}}


def test_normalize_flow_retention_policy_settings_preserves_invalid_supported_value() -> (
    None
):
    updated = normalize_flow_retention_policy_settings(
        {
            "retention_policy": {
                "source_audio_days": 3,
                "run_debug_evidence_days": "not-days",
            }
        }
    )

    assert updated["retention_policy"] == {"run_debug_evidence_days": "not-days"}
    with pytest.raises(ValueError, match="run_debug_evidence_days"):
        validate_flow_retention_policy_object(updated["retention_policy"])


def test_normalize_flow_retention_policy_settings_preserves_unknown_keys() -> None:
    updated = normalize_flow_retention_policy_settings(
        {
            "retention_policy": {
                "source_audio_days": 3,
                "unexpected_days": 7,
            }
        }
    )

    assert updated["retention_policy"] == {"unexpected_days": 7}
    with pytest.raises(ValueError, match="unknown fields: unexpected_days"):
        validate_flow_retention_policy_object(updated["retention_policy"])


def test_validate_flow_retention_policy_object_rejects_deleted_fields() -> None:
    with pytest.raises(ValueError, match="unknown fields: source_audio_days"):
        validate_flow_retention_policy_object({"source_audio_days": 3})


def test_validate_flow_retention_policy_object_accepts_supported_version() -> None:
    assert validate_flow_retention_policy_object(
        {"version": 1, "run_debug_evidence_days": 3}
    ) == {"version": 1, "run_debug_evidence_days": 3}


@pytest.mark.parametrize("version", [0, 2, True, "1"])
def test_validate_flow_retention_policy_object_rejects_unsupported_version(
    version,
) -> None:
    with pytest.raises(ValueError, match="retention_policy.version must be 1"):
        validate_flow_retention_policy_object(
            {"version": version, "run_debug_evidence_days": 3}
        )
