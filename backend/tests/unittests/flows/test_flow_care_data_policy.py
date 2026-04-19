from intric.flows.flow_care_data_policy import resolve_flow_care_data_policy


def test_resolve_flow_care_data_policy_reads_supported_fields() -> None:
    policy = resolve_flow_care_data_policy(
        {
            "care_data_policy": {
                "sensitive": True,
                "approval_mode": "single_reviewer_outside_flow",
                "pre_approval_visibility": "uploader_and_reviewers",
            }
        }
    )

    assert policy.sensitive is True
    assert policy.approval_mode == "single_reviewer_outside_flow"
    assert policy.pre_approval_visibility == "uploader_and_reviewers"


def test_resolve_flow_care_data_policy_defaults_when_metadata_absent() -> None:
    policy = resolve_flow_care_data_policy(None)

    assert policy.sensitive is False
    assert policy.approval_mode is None
    assert policy.pre_approval_visibility is None


def test_resolve_flow_care_data_policy_fails_closed_for_legacy_truthy_sensitive() -> (
    None
):
    policy = resolve_flow_care_data_policy({"care_data_policy": {"sensitive": "yes"}})

    assert policy.sensitive is True
    assert policy.approval_mode is None
    assert policy.pre_approval_visibility is None


def test_resolve_flow_care_data_policy_drops_unknown_enums() -> None:
    policy = resolve_flow_care_data_policy(
        {
            "care_data_policy": {
                "sensitive": True,
                "approval_mode": "two_reviewers",
                "pre_approval_visibility": "space_members",
            }
        }
    )

    assert policy.sensitive is True
    assert policy.approval_mode is None
    assert policy.pre_approval_visibility is None
