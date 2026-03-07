import { describe, expect, it } from "vitest";

import { shouldSaveAssistantImmediately } from "./assistantSavePolicy";

describe("shouldSaveAssistantImmediately", () => {
  it("requires immediate save for completion model changes", () => {
    expect(
      shouldSaveAssistantImmediately({
        completion_model: { id: "model-1" },
      }),
    ).toBe(true);
  });

  it("requires immediate save for completion model kwargs changes", () => {
    expect(
      shouldSaveAssistantImmediately({
        completion_model_kwargs: { temperature: 0.2 },
      }),
    ).toBe(true);
  });

  it("keeps prompt edits on the debounced path", () => {
    expect(
      shouldSaveAssistantImmediately({
        prompt: { text: "Summarize this" },
      }),
    ).toBe(false);
  });
});
