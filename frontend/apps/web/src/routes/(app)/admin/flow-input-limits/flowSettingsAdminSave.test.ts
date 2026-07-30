import type { AIBuilderBudgetSettings, FlowInputLimits } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

import { saveFlowAdminSettings } from "./flowSettingsAdminSave";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

describe("saveFlowAdminSettings", () => {
  it("waits for each shared settings write before starting the next", async () => {
    const inputResult = deferred<FlowInputLimits>();
    const builderResult = deferred<AIBuilderBudgetSettings>();
    let activeRequests = 0;
    let maxActiveRequests = 0;

    const updateFlowInputLimits = vi.fn(async () => {
      activeRequests += 1;
      maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
      try {
        return await inputResult.promise;
      } finally {
        activeRequests -= 1;
      }
    });
    const updateAIBuilderBudgetSettings = vi.fn(async () => {
      activeRequests += 1;
      maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
      try {
        return await builderResult.promise;
      } finally {
        activeRequests -= 1;
      }
    });
    const settings = {
      updateFlowInputLimits,
      updateFlowRuntimePolicy: vi.fn(),
      updateMappedExecutionPolicy: vi.fn(),
      updateAIBuilderBudgetSettings
    } as unknown as Parameters<typeof saveFlowAdminSettings>[0];

    const savePromise = saveFlowAdminSettings(settings, {
      inputLimits: { max_files_per_run: 20 },
      runtimePolicy: null,
      mappedExecution: null,
      builderBudget: { max_attachments: 50 }
    });

    await vi.waitFor(() => expect(updateFlowInputLimits).toHaveBeenCalledOnce());
    expect(updateAIBuilderBudgetSettings).not.toHaveBeenCalled();

    inputResult.resolve({
      file_max_size_bytes: 1,
      audio_max_size_bytes: 1,
      max_files_per_run: 20,
      audio_max_files_per_run: null
    });
    await vi.waitFor(() => expect(updateAIBuilderBudgetSettings).toHaveBeenCalledOnce());
    expect(maxActiveRequests).toBe(1);

    builderResult.resolve({
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
    });

    await expect(savePromise).resolves.toMatchObject({
      inputLimits: { max_files_per_run: 20 },
      builderBudget: { max_attachments: 50 }
    });
    expect(maxActiveRequests).toBe(1);
  });
});
