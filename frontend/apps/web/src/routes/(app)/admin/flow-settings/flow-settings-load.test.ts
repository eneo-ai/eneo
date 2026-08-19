import { describe, expect, it, vi } from "vitest";

import { load } from "./+page";

describe("flow settings load", () => {
  it("loads every flow policy, including classification-specific retention rules", async () => {
    const values = {
      flowRetentionPolicy: { id: "retention" },
      flowInputLimits: { id: "input" },
      flowRuntimePolicy: { id: "runtime" },
      mappedExecutionPolicy: { id: "mapped" },
      ragEvidencePolicy: { id: "evidence" },
      securityClassifications: { security_enabled: true, security_classifications: [] },
      flowClassificationRetentionPolicies: { policies: [] }
    };
    const eneo = {
      settings: {
        getFlowRetentionPolicy: vi.fn().mockResolvedValue(values.flowRetentionPolicy),
        getFlowInputLimits: vi.fn().mockResolvedValue(values.flowInputLimits),
        getFlowRuntimePolicy: vi.fn().mockResolvedValue(values.flowRuntimePolicy),
        getMappedExecutionPolicy: vi.fn().mockResolvedValue(values.mappedExecutionPolicy),
        getRagEvidencePolicy: vi.fn().mockResolvedValue(values.ragEvidencePolicy),
        listFlowClassificationRetentionPolicies: vi
          .fn()
          .mockResolvedValue(values.flowClassificationRetentionPolicies)
      },
      securityClassifications: {
        list: vi.fn().mockResolvedValue(values.securityClassifications)
      }
    };

    const result = await load({ parent: async () => ({ eneo }) } as never);

    expect(result).toEqual(values);
    expect(eneo.securityClassifications.list).toHaveBeenCalledOnce();
    expect(eneo.settings.listFlowClassificationRetentionPolicies).toHaveBeenCalledOnce();
  });
});
