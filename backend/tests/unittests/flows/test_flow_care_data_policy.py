import re

import pytest

from intric.flows.flow_care_data_policy import (
    resolve_flow_care_data_policy,
    validate_flow_care_data_policy,
)
from intric.flows.flow_metadata import FlowCareDataPolicyV1
from intric.main.exceptions import BadRequestException


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


def test_resolve_flow_care_data_policy_returns_canonical_metadata_policy() -> None:
    policy = resolve_flow_care_data_policy(None)

    assert isinstance(policy, FlowCareDataPolicyV1)


@pytest.mark.parametrize(
    ("metadata_json", "message"),
    [
        (
            {"care_data_policy": []},
            "metadata_json.care_data_policy must be an object.",
        ),
        (
            {"care_data_policy": {"unknown": True}},
            "metadata_json.care_data_policy contains unknown fields: unknown",
        ),
        (
            {"care_data_policy": {"sensitive": "yes"}},
            "metadata_json.care_data_policy.sensitive must be a boolean.",
        ),
        (
            {"care_data_policy": {"approval_mode": "two_reviewers"}},
            "metadata_json.care_data_policy.approval_mode must be 'single_reviewer_outside_flow' when provided.",
        ),
        (
            {"care_data_policy": {"pre_approval_visibility": "everyone"}},
            "metadata_json.care_data_policy.pre_approval_visibility must be 'uploader_and_reviewers' when provided.",
        ),
    ],
)
def test_validate_flow_care_data_policy_preserves_write_errors(
    metadata_json: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BadRequestException, match=re.escape(message)):
        validate_flow_care_data_policy(metadata_json)


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
