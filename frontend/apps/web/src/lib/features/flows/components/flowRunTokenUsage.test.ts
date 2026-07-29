import { describe, expect, it } from "vitest";

import { buildFlowRunTokenUsageView, formatFlowRunTokenCount } from "./flowRunTokenUsage";

describe("flowRunTokenUsage", () => {
  it("distinguishes missing usage from reported zero usage", () => {
    expect(buildFlowRunTokenUsageView(null)).toEqual({ kind: "not_recorded" });
    expect(
      buildFlowRunTokenUsageView({
        num_tokens_input: 0,
        num_tokens_output: 0,
        num_tokens_total: 0,
        input_completeness: "complete",
        output_completeness: "complete"
      })
    ).toEqual({
      kind: "recorded",
      total: 0,
      input: 0,
      output: 0,
      incomplete: false,
      inputIncomplete: false,
      outputIncomplete: false
    });
  });

  it("normalizes provider-reported run usage for the UI", () => {
    expect(
      buildFlowRunTokenUsageView({
        num_tokens_input: 1200,
        num_tokens_output: 300,
        num_tokens_total: 1500,
        input_completeness: "incomplete",
        output_completeness: "complete"
      })
    ).toEqual({
      kind: "recorded",
      total: 1500,
      input: 1200,
      output: 300,
      incomplete: true,
      inputIncomplete: true,
      outputIncomplete: false
    });
  });

  it("formats compact and full token counts without a UI runtime", () => {
    expect(formatFlowRunTokenCount(1500, "en", { compact: true })).toBe("1.5K");
    expect(formatFlowRunTokenCount(1500, "en")).toBe("1,500");
  });
});
