from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from intric.main.exceptions import BadRequestException

CareDataApprovalMode = Literal["single_reviewer_outside_flow"]
CareDataPreApprovalVisibility = Literal["uploader_and_reviewers"]
SUPPORTED_CARE_DATA_APPROVAL_MODES = frozenset({"single_reviewer_outside_flow"})
SUPPORTED_CARE_DATA_PRE_APPROVAL_VISIBILITY = frozenset({"uploader_and_reviewers"})


@dataclass(frozen=True)
class FlowCareDataPolicy:
    sensitive: bool = False
    approval_mode: CareDataApprovalMode | None = None
    pre_approval_visibility: CareDataPreApprovalVisibility | None = None


def resolve_flow_care_data_policy(
    metadata_json: dict[str, Any] | None,
) -> FlowCareDataPolicy:
    if not isinstance(metadata_json, dict):
        return FlowCareDataPolicy()
    care_data_policy = metadata_json.get("care_data_policy")
    if not isinstance(care_data_policy, dict):
        return FlowCareDataPolicy()
    policy_dict = cast(dict[str, Any], care_data_policy)
    approval_mode = policy_dict.get("approval_mode")
    pre_approval_visibility = policy_dict.get("pre_approval_visibility")
    sensitive_value = policy_dict.get("sensitive", False)
    return FlowCareDataPolicy(
        # Fail closed for legacy truthy values that predate strict authoring
        # validation; writes must still pass validate_flow_care_data_policy.
        sensitive=bool(sensitive_value),
        approval_mode=approval_mode
        if approval_mode in SUPPORTED_CARE_DATA_APPROVAL_MODES
        else None,
        pre_approval_visibility=pre_approval_visibility
        if pre_approval_visibility in SUPPORTED_CARE_DATA_PRE_APPROVAL_VISIBILITY
        else None,
    )


def validate_flow_care_data_policy(metadata_json: dict[str, Any] | None) -> None:
    if metadata_json is None:
        return
    care_data_policy = metadata_json.get("care_data_policy")
    if care_data_policy is None:
        return
    if not isinstance(care_data_policy, dict):
        raise BadRequestException("metadata_json.care_data_policy must be an object.")
    policy_dict = cast(dict[str, Any], care_data_policy)
    allowed_fields = {"sensitive", "approval_mode", "pre_approval_visibility"}
    unknown_fields = set(policy_dict) - allowed_fields
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise BadRequestException(
            f"metadata_json.care_data_policy contains unknown fields: {unknown}"
        )
    sensitive = policy_dict.get("sensitive")
    if sensitive is not None and not isinstance(sensitive, bool):
        raise BadRequestException(
            "metadata_json.care_data_policy.sensitive must be a boolean."
        )
    approval_mode = policy_dict.get("approval_mode")
    if (
        approval_mode is not None
        and approval_mode not in SUPPORTED_CARE_DATA_APPROVAL_MODES
    ):
        raise BadRequestException(
            "metadata_json.care_data_policy.approval_mode must be 'single_reviewer_outside_flow' when provided."
        )
    pre_approval_visibility = policy_dict.get("pre_approval_visibility")
    if (
        pre_approval_visibility is not None
        and pre_approval_visibility not in SUPPORTED_CARE_DATA_PRE_APPROVAL_VISIBILITY
    ):
        raise BadRequestException(
            "metadata_json.care_data_policy.pre_approval_visibility must be 'uploader_and_reviewers' when provided."
        )
