import { describe, expect, it, vi } from "vitest";

import { load } from "./+page";

const values = {
  flowRetentionPolicy: { id: "retention" },
  flowRunRetentionPolicy: { id: "run-retention" },
  flowRunRetentionReviewQueue: { items: [], count: 0, has_more: false, next_cursor: null },
  spaceTargets: { items: [{ id: "space-1", name: "Operations" }], count: 1, has_more: true },
  flowRetentionHolds: { items: [], has_more: false, review_limit_days: 365 },
  holdReviewLimit: { days: 365, is_default: true },
  flowInputLimits: { id: "input" },
  flowRuntimePolicy: { id: "runtime" },
  mappedExecutionPolicy: { id: "mapped" },
  aiBuilderBudgetSettings: { id: "builder" },
  ragEvidencePolicy: { id: "evidence" }
};

function eneoMock() {
  return {
    settings: {
      getFlowRetentionPolicy: vi.fn().mockResolvedValue(values.flowRetentionPolicy),
      getOrganizationFlowRunRetentionPolicy: vi
        .fn()
        .mockResolvedValue(values.flowRunRetentionPolicy),
      listOrganizationFlowRunRetentionReviewQueue: vi
        .fn()
        .mockResolvedValue(values.flowRunRetentionReviewQueue),
      listFlowRunRetentionSpaceTargets: vi.fn().mockResolvedValue(values.spaceTargets),
      listFlowRetentionHolds: vi.fn().mockResolvedValue(values.flowRetentionHolds),
      getFlowRetentionHoldReviewLimit: vi.fn().mockResolvedValue(values.holdReviewLimit),
      getFlowInputLimits: vi.fn().mockResolvedValue(values.flowInputLimits),
      getFlowRuntimePolicy: vi.fn().mockResolvedValue(values.flowRuntimePolicy),
      getMappedExecutionPolicy: vi.fn().mockResolvedValue(values.mappedExecutionPolicy),
      getAIBuilderBudgetSettings: vi.fn().mockResolvedValue(values.aiBuilderBudgetSettings),
      getRagEvidencePolicy: vi.fn().mockResolvedValue(values.ragEvidencePolicy)
    }
  };
}

function userWith(...permissions: string[]) {
  return { roles: [{ permissions }], predefined_roles: [] };
}

async function loadFor(eneo: ReturnType<typeof eneoMock>, user: object) {
  return await load({ parent: async () => ({ eneo, user }) } as never);
}

describe("flow settings load", () => {
  it("loads every current flow policy for an admin with both retention permissions", async () => {
    const eneo = eneoMock();
    const result = await loadFor(eneo, userWith("admin", "retention_manage", "retention_holds"));

    expect(result).toEqual({
      access: { admin: true, retentionManage: true, retentionHolds: true },
      ...values
    });
    expect(eneo.settings.listFlowRunRetentionSpaceTargets).toHaveBeenCalledExactlyOnceWith({
      limit: 200,
      offset: 0
    });
    expect(eneo.settings.listFlowRetentionHolds).toHaveBeenCalledExactlyOnceWith({ limit: 200 });
  });

  it("asks a holds-only role for retention data and holds, never for admin settings", async () => {
    const eneo = eneoMock();
    const result = await loadFor(eneo, userWith("retention_holds"));

    expect(result.access).toEqual({ admin: false, retentionManage: false, retentionHolds: true });
    expect(result.flowRetentionHolds).toEqual(values.flowRetentionHolds);
    expect(result.holdReviewLimit).toEqual(values.holdReviewLimit);
    expect(result.flowRunRetentionPolicy).toEqual(values.flowRunRetentionPolicy);
    expect(result.flowRunRetentionReviewQueue).toBeNull();
    expect(result.flowInputLimits).toBeNull();
    for (const call of [
      eneo.settings.getFlowRetentionPolicy,
      eneo.settings.getFlowInputLimits,
      eneo.settings.getFlowRuntimePolicy,
      eneo.settings.getMappedExecutionPolicy,
      eneo.settings.getAIBuilderBudgetSettings,
      eneo.settings.getRagEvidencePolicy,
      eneo.settings.listOrganizationFlowRunRetentionReviewQueue
    ]) {
      expect(call).not.toHaveBeenCalled();
    }
  });

  it("asks a rules-only role for the review queue but not for holds", async () => {
    const eneo = eneoMock();
    const result = await loadFor(eneo, userWith("retention_manage"));

    expect(result.flowRunRetentionReviewQueue).toEqual(values.flowRunRetentionReviewQueue);
    expect(result.flowRetentionHolds).toBeNull();
    expect(eneo.settings.listFlowRetentionHolds).not.toHaveBeenCalled();
    expect(eneo.settings.getFlowRetentionPolicy).not.toHaveBeenCalled();
  });

  it("asks an admin without retention permissions for no retention data", async () => {
    const eneo = eneoMock();
    const result = await loadFor(eneo, userWith("admin"));

    expect(result.flowRunRetentionPolicy).toBeNull();
    expect(result.spaceTargets).toBeNull();
    expect(result.holdReviewLimit).toBeNull();
    expect(result.flowRetentionPolicy).toEqual(values.flowRetentionPolicy);
    expect(eneo.settings.getOrganizationFlowRunRetentionPolicy).not.toHaveBeenCalled();
  });

  it("keeps policy settings available when the review queue and holds cannot load", async () => {
    const eneo = eneoMock();
    eneo.settings.listOrganizationFlowRunRetentionReviewQueue.mockRejectedValue(
      new Error("queue unavailable")
    );
    eneo.settings.listFlowRetentionHolds.mockRejectedValue(new Error("holds unavailable"));
    const result = await loadFor(eneo, userWith("admin", "retention_manage", "retention_holds"));

    expect(result.flowRunRetentionPolicy).toEqual(values.flowRunRetentionPolicy);
    expect(result.flowRunRetentionReviewQueue).toBeNull();
    expect(result.flowRetentionHolds).toBeNull();
  });
});
