import type { FlowRagEvidencePolicy, FlowRuntimePolicy } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

import { saveFlowAdminSettings } from "./flowSettingsAdminSave";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

const RUNTIME_POLICY = {
  default_step_timeout_seconds: 900,
  max_step_timeout_seconds: 1800,
  hard_ceiling_seconds: 3600
} as FlowRuntimePolicy;

const RAG_EVIDENCE: FlowRagEvidencePolicy = {
  max_sources_with_recorded_passages: 25,
  max_recorded_passages_per_source: 5,
  max_recorded_passage_bytes: 4_096,
  max_recorded_passage_bytes_per_step: 131_072,
  max_recorded_passage_bytes_per_run_view: 2_097_152
};

describe("saveFlowAdminSettings", () => {
  it("waits for each shared settings write before starting the next", async () => {
    const runtimeResult = deferred<FlowRuntimePolicy>();
    const ragResult = deferred<FlowRagEvidencePolicy>();
    let activeRequests = 0;
    let maxActiveRequests = 0;

    const track = async <T>(promise: Promise<T>) => {
      activeRequests += 1;
      maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
      try {
        return await promise;
      } finally {
        activeRequests -= 1;
      }
    };

    const updateFlowRuntimePolicy = vi.fn(() => track(runtimeResult.promise));
    const updateRagEvidencePolicy = vi.fn(() => track(ragResult.promise));
    const settings = {
      updateFlowInputLimits: vi.fn(),
      updateFlowRuntimePolicy,
      updateMappedExecutionPolicy: vi.fn(),
      updateRagEvidencePolicy
    } as unknown as Parameters<typeof saveFlowAdminSettings>[0];

    const savePromise = saveFlowAdminSettings(settings, {
      inputLimits: null,
      runtimePolicy: { default_step_timeout_seconds: 900 },
      mappedExecution: null,
      ragEvidence: { max_recorded_passages_per_source: 5 }
    });

    await vi.waitFor(() => expect(updateFlowRuntimePolicy).toHaveBeenCalledOnce());
    expect(updateRagEvidencePolicy).not.toHaveBeenCalled();

    runtimeResult.resolve(RUNTIME_POLICY);
    await vi.waitFor(() => expect(updateRagEvidencePolicy).toHaveBeenCalledOnce());
    expect(maxActiveRequests).toBe(1);

    ragResult.resolve(RAG_EVIDENCE);

    await expect(savePromise).resolves.toMatchObject({
      runtimePolicy: { default_step_timeout_seconds: 900 },
      ragEvidence: { max_recorded_passages_per_source: 5 }
    });
    expect(maxActiveRequests).toBe(1);
  });

  it("skips endpoints without a patch", async () => {
    const settings = {
      updateFlowInputLimits: vi.fn(),
      updateFlowRuntimePolicy: vi.fn(),
      updateMappedExecutionPolicy: vi.fn(),
      updateRagEvidencePolicy: vi.fn()
    } as unknown as Parameters<typeof saveFlowAdminSettings>[0];

    await expect(
      saveFlowAdminSettings(settings, {
        inputLimits: null,
        runtimePolicy: null,
        mappedExecution: null,
        ragEvidence: null
      })
    ).resolves.toEqual({
      inputLimits: null,
      runtimePolicy: null,
      mappedExecution: null,
      ragEvidence: null
    });
  });
});
