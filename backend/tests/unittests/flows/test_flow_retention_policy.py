from intric.flows.flow_retention_policy import (
    FlowRetentionPolicy,
    apply_flow_retention_policy_patch,
    resolve_flow_retention_policy,
)


def test_resolve_flow_retention_policy_reads_shared_default_and_overrides() -> None:
    policy = resolve_flow_retention_policy(
        {
            "retention_policy": {
                "shared_default_days": 30,
                "source_audio_days": 3,
                "transcript_text_days": 7,
            }
        }
    )

    assert policy.shared_default_days == 30
    assert policy.source_audio_days == 3
    assert policy.transcript_text_days == 7


def test_flow_retention_policy_resolves_precedence_flow_then_class_then_space_then_shared() -> (
    None
):
    policy = FlowRetentionPolicy(
        shared_default_days=30,
        source_audio_days=3,
        transcript_text_days=7,
    )

    assert (
        policy.retention_for_class(
            "source_audio",
            space_default_days=14,
            flow_override_days=1,
        )
        == 1
    )
    assert (
        policy.retention_for_class(
            "source_audio",
            space_default_days=14,
            flow_override_days=None,
        )
        == 3
    )
    assert (
        policy.retention_for_class(
            "generated_artifact",
            space_default_days=14,
            flow_override_days=None,
        )
        == 14
    )
    assert (
        policy.retention_for_class(
            "run_debug_evidence",
            space_default_days=None,
            flow_override_days=None,
        )
        == 30
    )


def test_apply_flow_retention_policy_patch_can_remove_override() -> None:
    updated = apply_flow_retention_policy_patch(
        {
            "retention_policy": {
                "shared_default_days": 30,
                "source_audio_days": 3,
            }
        },
        source_audio_days=None,
        remove_keys={"source_audio_days"},
    )

    assert updated["retention_policy"]["shared_default_days"] == 30
    assert "source_audio_days" not in updated["retention_policy"]
