import pytest

from intric.flows.flow_retention_policy import (
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


def test_flow_retention_policy_resolves_precedence_flow_then_debug_then_space() -> None:
    policy = FlowRetentionPolicy(run_debug_evidence_days=7)

    assert (
        policy.retention_for_class(
            "run_debug_evidence",
            space_default_days=14,
            flow_override_days=1,
        )
        == 1
    )
    assert (
        policy.retention_for_class(
            "run_debug_evidence",
            space_default_days=14,
            flow_override_days=None,
        )
        == 7
    )
    assert (
        FlowRetentionPolicy().retention_for_class(
            "run_debug_evidence",
            space_default_days=14,
            flow_override_days=None,
        )
        == 14
    )
    assert (
        FlowRetentionPolicy().retention_for_class(
            "run_debug_evidence",
            space_default_days=None,
            flow_override_days=None,
        )
        is None
    )


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

    assert updated["retention_policy"] == {"run_debug_evidence_days": 30}


def test_apply_flow_retention_policy_patch_can_remove_debug_evidence_override() -> None:
    updated = apply_flow_retention_policy_patch(
        {"retention_policy": {"run_debug_evidence_days": 14}},
        run_debug_evidence_days=None,
        remove_keys={"run_debug_evidence_days"},
    )

    assert "retention_policy" not in updated


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


def test_validate_flow_retention_policy_object_rejects_deleted_fields() -> None:
    with pytest.raises(ValueError, match="unknown fields: source_audio_days"):
        validate_flow_retention_policy_object({"source_audio_days": 3})
