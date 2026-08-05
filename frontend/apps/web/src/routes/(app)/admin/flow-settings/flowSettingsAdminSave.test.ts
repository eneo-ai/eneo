import type { AIBuilderBudgetSettings, FlowRagEvidencePolicy } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

import { saveFlowAdminSettings } from "./flowSettingsAdminSave";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

const BUILDER_BUDGET: AIBuilderBudgetSettings = {
  conversation_safety_buffer_tokens: 2_000,
  minimum_conversation_budget_tokens: 4_000,
  max_attachments: 50,
  max_message_chars: 50_000,
  max_template_inspection_uncompressed_bytes: 200 * 1024 * 1024,
  max_template_placeholders: 1_000,
  max_attachments_hard_limit: 100,
  max_message_chars_hard_limit: 50_000,
  max_template_inspection_uncompressed_bytes_hard_limit: 200 * 1024 * 1024,
  max_template_placeholders_hard_limit: 10_000,
  max_template_archive_entries_per_file_hard_limit: 2_048,
  max_template_uncompressed_bytes_per_file_hard_limit: 50 * 1024 * 1024,
  max_planning_state_payload_bytes_hard_limit: 128 * 1024,
  budget_token_hard_limit: 10_000_000
};

const RAG_EVIDENCE: FlowRagEvidencePolicy = {
  max_sources_with_recorded_passages: 25,
  max_recorded_passages_per_source: 5,
  max_recorded_passage_bytes: 4_096,
  max_recorded_passage_bytes_per_step: 131_072,
  max_recorded_passage_bytes_per_run_view: 2_097_152
};

describe("saveFlowAdminSettings", () => {
  it("waits for each shared settings write before starting the next", async () => {
    const builderResult = deferred<AIBuilderBudgetSettings>();
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

    const updateAIBuilderBudgetSettings = vi.fn(() => track(builderResult.promise));
    const updateRagEvidencePolicy = vi.fn(() => track(ragResult.promise));
    const settings = {
      updateFlowInputLimits: vi.fn(),
      updateFlowRuntimePolicy: vi.fn(),
      updateMappedExecutionPolicy: vi.fn(),
      updateAIBuilderBudgetSettings,
      updateRagEvidencePolicy
    } as unknown as Parameters<typeof saveFlowAdminSettings>[0];

    const savePromise = saveFlowAdminSettings(settings, {
      inputLimits: null,
      runtimePolicy: null,
      mappedExecution: null,
      builderBudget: { max_attachments: 50 },
      ragEvidence: { max_recorded_passages_per_source: 5 }
    });

    await vi.waitFor(() => expect(updateAIBuilderBudgetSettings).toHaveBeenCalledOnce());
    expect(updateRagEvidencePolicy).not.toHaveBeenCalled();

    builderResult.resolve(BUILDER_BUDGET);
    await vi.waitFor(() => expect(updateRagEvidencePolicy).toHaveBeenCalledOnce());
    expect(maxActiveRequests).toBe(1);

    ragResult.resolve(RAG_EVIDENCE);

    await expect(savePromise).resolves.toMatchObject({
      builderBudget: { max_attachments: 50 },
      ragEvidence: { max_recorded_passages_per_source: 5 }
    });
    expect(maxActiveRequests).toBe(1);
  });

  it("skips endpoints without a patch", async () => {
    const settings = {
      updateFlowInputLimits: vi.fn(),
      updateFlowRuntimePolicy: vi.fn(),
      updateMappedExecutionPolicy: vi.fn(),
      updateAIBuilderBudgetSettings: vi.fn(),
      updateRagEvidencePolicy: vi.fn()
    } as unknown as Parameters<typeof saveFlowAdminSettings>[0];

    await expect(
      saveFlowAdminSettings(settings, {
        inputLimits: null,
        runtimePolicy: null,
        mappedExecution: null,
        builderBudget: null,
        ragEvidence: null
      })
    ).resolves.toEqual({
      inputLimits: null,
      runtimePolicy: null,
      mappedExecution: null,
      builderBudget: null,
      ragEvidence: null
    });
  });
});
