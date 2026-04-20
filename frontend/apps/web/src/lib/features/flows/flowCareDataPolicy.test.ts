import { describe, expect, it } from "vitest";

import { resolveFlowCareDataPolicy } from "./flowCareDataPolicy";

describe("flowCareDataPolicy", () => {
  it("reads supported sensitive flow policy fields", () => {
    expect(
      resolveFlowCareDataPolicy({
        care_data_policy: {
          sensitive: true,
          approval_mode: "single_reviewer_outside_flow",
          pre_approval_visibility: "uploader_and_reviewers"
        }
      })
    ).toEqual({
      sensitive: true,
      approvalMode: "single_reviewer_outside_flow",
      preApprovalVisibility: "uploader_and_reviewers"
    });
  });

  it("falls back safely when metadata is absent", () => {
    expect(resolveFlowCareDataPolicy(null)).toEqual({
      sensitive: false,
      approvalMode: null,
      preApprovalVisibility: null
    });
  });

  it("drops unsupported enum values and non-object policies", () => {
    expect(
      resolveFlowCareDataPolicy({
        care_data_policy: {
          sensitive: true,
          approval_mode: "two_reviewers",
          pre_approval_visibility: "space_members"
        }
      })
    ).toEqual({
      sensitive: true,
      approvalMode: null,
      preApprovalVisibility: null
    });

    expect(resolveFlowCareDataPolicy({ care_data_policy: [] })).toEqual({
      sensitive: false,
      approvalMode: null,
      preApprovalVisibility: null
    });
  });
});
