export type FlowCareDataPolicy = {
  sensitive: boolean;
  approvalMode: "single_reviewer_outside_flow" | null;
  preApprovalVisibility: "uploader_and_reviewers" | null;
};

export function resolveFlowCareDataPolicy(metadataJson: unknown): FlowCareDataPolicy {
  if (!metadataJson || typeof metadataJson !== "object") {
    return {
      sensitive: false,
      approvalMode: null,
      preApprovalVisibility: null
    };
  }

  const careDataPolicy = (metadataJson as Record<string, unknown>).care_data_policy;
  if (!careDataPolicy || typeof careDataPolicy !== "object") {
    return {
      sensitive: false,
      approvalMode: null,
      preApprovalVisibility: null
    };
  }

  const policy = careDataPolicy as Record<string, unknown>;
  return {
    sensitive: Boolean(policy.sensitive),
    approvalMode:
      policy.approval_mode === "single_reviewer_outside_flow"
        ? "single_reviewer_outside_flow"
        : null,
    preApprovalVisibility:
      policy.pre_approval_visibility === "uploader_and_reviewers" ? "uploader_and_reviewers" : null
  };
}
