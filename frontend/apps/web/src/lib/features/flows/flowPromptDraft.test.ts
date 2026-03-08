import { describe, expect, it } from "vitest";

import { buildNextFlowPrompt } from "./flowPromptDraft";

describe("buildNextFlowPrompt", () => {
  it("preserves the existing description when updating prompt text", () => {
    expect(buildNextFlowPrompt({ text: "Old", description: "Keep me" }, "New")).toEqual({
      text: "New",
      description: "Keep me"
    });
  });

  it("falls back to an empty description when the prompt is missing", () => {
    expect(buildNextFlowPrompt(undefined, "Prompt")).toEqual({
      text: "Prompt",
      description: ""
    });
  });
});
