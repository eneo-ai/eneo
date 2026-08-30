import { describe, expect, it, vi } from "vitest";

import { load } from "./+page";

describe("flow settings load", () => {
  it("loads every current flow policy", async () => {
    const values = {
      flowRetentionPolicy: { id: "retention" },
      flowRunRetentionPolicy: { id: "run-retention" },
      flowRunRetentionReviewQueue: {
        items: [],
        count: 0,
        has_more: false,
        next_cursor: null
      },
      spaceTargets: {
        items: [{ id: "space-1", name: "Operations" }],
        count: 1,
        has_more: true
      },
      flowInputLimits: { id: "input" },
      flowRuntimePolicy: { id: "runtime" },
      mappedExecutionPolicy: { id: "mapped" },
      aiBuilderBudgetSettings: { id: "builder" },
      ragEvidencePolicy: { id: "evidence" }
    };
    const eneo = {
      settings: {
        getFlowRetentionPolicy: vi.fn().mockResolvedValue(values.flowRetentionPolicy),
        getOrganizationFlowRunRetentionPolicy: vi
          .fn()
          .mockResolvedValue(values.flowRunRetentionPolicy),
        listOrganizationFlowRunRetentionReviewQueue: vi
          .fn()
          .mockResolvedValue(values.flowRunRetentionReviewQueue),
        listFlowRunRetentionSpaceTargets: vi.fn().mockResolvedValue({
          ...values.spaceTargets
        }),
        getFlowInputLimits: vi.fn().mockResolvedValue(values.flowInputLimits),
        getFlowRuntimePolicy: vi.fn().mockResolvedValue(values.flowRuntimePolicy),
        getMappedExecutionPolicy: vi.fn().mockResolvedValue(values.mappedExecutionPolicy),
        getAIBuilderBudgetSettings: vi.fn().mockResolvedValue(values.aiBuilderBudgetSettings),
        getRagEvidencePolicy: vi.fn().mockResolvedValue(values.ragEvidencePolicy)
      }
    };

    const result = await load({ parent: async () => ({ eneo }) } as never);
    expect(result).toEqual(values);
    expect(eneo.settings.listFlowRunRetentionSpaceTargets).toHaveBeenCalledExactlyOnceWith({
      limit: 200,
      offset: 0
    });
  });

  it("keeps policy settings available when the review queue cannot load", async () => {
    const eneo = {
      settings: {
        getFlowRetentionPolicy: vi.fn().mockResolvedValue({ id: "retention" }),
        getOrganizationFlowRunRetentionPolicy: vi.fn().mockResolvedValue({
          id: "run-retention"
        }),
        listOrganizationFlowRunRetentionReviewQueue: vi
          .fn()
          .mockRejectedValue(new Error("queue unavailable")),
        listFlowRunRetentionSpaceTargets: vi.fn().mockResolvedValue({
          items: [],
          count: 0,
          has_more: false
        }),
        getFlowInputLimits: vi.fn().mockResolvedValue({ id: "input" }),
        getFlowRuntimePolicy: vi.fn().mockResolvedValue({ id: "runtime" }),
        getMappedExecutionPolicy: vi.fn().mockResolvedValue({ id: "mapped" }),
        getAIBuilderBudgetSettings: vi.fn().mockResolvedValue({ id: "builder" }),
        getRagEvidencePolicy: vi.fn().mockResolvedValue({ id: "evidence" })
      }
    };

    const result = await load({ parent: async () => ({ eneo }) } as never);

    expect(result.flowRunRetentionPolicy).toEqual({ id: "run-retention" });
    expect(result.flowRunRetentionReviewQueue).toBeNull();
  });
});
