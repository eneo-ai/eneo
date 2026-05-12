import { describe, expect, it } from "vitest";

import { buildFlowRunTokenUsageView, formatFlowRunTokenCount } from "./flowRunTokenUsage";

describe("flowRunTokenUsage", () => {
  it("does not create a display model for missing or empty usage", () => {
    expect(buildFlowRunTokenUsageView(null)).toBeNull();
    expect(
      buildFlowRunTokenUsageView({
        num_tokens_input: 10,
        num_tokens_output: 5,
        num_tokens_total: 0
      })
    ).toBeNull();
  });

  it("normalizes provider-reported run usage for the UI", () => {
    expect(
      buildFlowRunTokenUsageView({
        num_tokens_input: 1200,
        num_tokens_output: 300,
        num_tokens_total: 1500
      })
    ).toEqual({
      total: 1500,
      input: 1200,
      output: 300
    });
  });

  it("formats compact and full token counts without a UI runtime", () => {
    expect(formatFlowRunTokenCount(1500, "en", { compact: true })).toBe("1.5K");
    expect(formatFlowRunTokenCount(1500, "en")).toBe("1,500");
  });
});
