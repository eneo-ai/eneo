import type { FlowMappedExecutionPolicy, FlowRagEvidencePolicy } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

import { saveFlowAdminSettings } from "./flowSettingsAdminSave";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

const MAPPED_EXECUTION = {
  version: 1,
  max_provider_calls_per_mapped_step: 40,
  max_estimated_input_tokens_per_mapped_step: null,
  max_provider_calls_source: "organization",
  deployment_default_max_provider_calls: 100
} as unknown as FlowMappedExecutionPolicy;

const RAG_EVIDENCE: FlowRagEvidencePolicy = {
  max_sources_with_recorded_passages: 25,
  max_recorded_passages_per_source: 5,
  max_recorded_passage_bytes: 4_096,
  max_recorded_passage_bytes_per_step: 131_072,
  max_recorded_passage_bytes_per_run_view: 2_097_152
};

describe("saveFlowAdminSettings", () => {
  it("waits for each shared settings write before starting the next", async () => {
    const mappedResult = deferred<FlowMappedExecutionPolicy>();
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

    const updateMappedExecutionPolicy = vi.fn(() => track(mappedResult.promise));
    const updateRagEvidencePolicy = vi.fn(() => track(ragResult.promise));
    const settings = {
      updateFlowInputLimits: vi.fn(),
      updateFlowRuntimePolicy: vi.fn(),
      updateMappedExecutionPolicy,
      updateRagEvidencePolicy
    } as unknown as Parameters<typeof saveFlowAdminSettings>[0];

    const savePromise = saveFlowAdminSettings(settings, {
      inputLimits: null,
      runtimePolicy: null,
      mappedExecution: { max_provider_calls_per_mapped_step: 40 },
      ragEvidence: { max_recorded_passages_per_source: 5 }
    });

    await vi.waitFor(() => expect(updateMappedExecutionPolicy).toHaveBeenCalledOnce());
    expect(updateRagEvidencePolicy).not.toHaveBeenCalled();

    mappedResult.resolve(MAPPED_EXECUTION);
    await vi.waitFor(() => expect(updateRagEvidencePolicy).toHaveBeenCalledOnce());
    expect(maxActiveRequests).toBe(1);

    ragResult.resolve(RAG_EVIDENCE);

    await expect(savePromise).resolves.toMatchObject({
      mappedExecution: { max_provider_calls_per_mapped_step: 40 },
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

describe("isRunCapacityExceededError", () => {
  it("recognises only the server capacity refusal", async () => {
    const { EneoError } = await import("@eneo/eneo-js");
    const { isRunCapacityExceededError } = await import("./flowSettingsAdminSave");

    expect(
      isRunCapacityExceededError(
        new EneoError("x", "SERVER", 400, 9007, {
          code: "max_concurrent_runs_exceeds_server_capacity"
        })
      )
    ).toBe(true);
    expect(
      isRunCapacityExceededError(new EneoError("x", "SERVER", 400, 9007, { code: "other" }))
    ).toBe(false);
    expect(isRunCapacityExceededError(new Error("x"))).toBe(false);
    expect(isRunCapacityExceededError(null)).toBe(false);
  });
});
