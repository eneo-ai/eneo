import { describe, expect, it, vi } from "vitest";

import { load } from "./+page";

describe("flow settings load", () => {
  it("loads every current flow policy", async () => {
    const values = {
      flowRetentionPolicy: { id: "retention" },
      flowInputLimits: { id: "input" },
      flowRuntimePolicy: { id: "runtime" },
      mappedExecutionPolicy: { id: "mapped" },
      aiBuilderBudgetSettings: { id: "builder" },
      ragEvidencePolicy: { id: "evidence" }
    };
    const eneo = {
      settings: {
        getFlowRetentionPolicy: vi.fn().mockResolvedValue(values.flowRetentionPolicy),
        getFlowInputLimits: vi.fn().mockResolvedValue(values.flowInputLimits),
        getFlowRuntimePolicy: vi.fn().mockResolvedValue(values.flowRuntimePolicy),
        getMappedExecutionPolicy: vi.fn().mockResolvedValue(values.mappedExecutionPolicy),
        getAIBuilderBudgetSettings: vi.fn().mockResolvedValue(values.aiBuilderBudgetSettings),
        getRagEvidencePolicy: vi.fn().mockResolvedValue(values.ragEvidencePolicy)
      }
    };

    const result = await load({ parent: async () => ({ eneo }) } as never);
    expect(result).toEqual(values);
  });
});
