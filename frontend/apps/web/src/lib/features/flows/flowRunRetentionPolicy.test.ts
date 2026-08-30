import { describe, expect, it } from "vitest";

import { flowRunRetentionPoliciesEqual, parseFlowRunRetentionDays } from "./flowRunRetentionPolicy";

describe("Flow run-retention policy form rules", () => {
  it("accepts only bare integers inside the public range", () => {
    expect(parseFlowRunRetentionDays("1")).toBe(1);
    expect(parseFlowRunRetentionDays(30)).toBe(30);
    expect(parseFlowRunRetentionDays(" 2555 ")).toBe(2555);
    expect(parseFlowRunRetentionDays("2.9")).toBeNull();
    expect(parseFlowRunRetentionDays("1e2")).toBeNull();
    expect(parseFlowRunRetentionDays("0")).toBeNull();
    expect(parseFlowRunRetentionDays("2556")).toBeNull();
    expect(parseFlowRunRetentionDays("")).toBeNull();
  });

  it("compares the complete mode-and-days policy", () => {
    expect(
      flowRunRetentionPoliciesEqual(
        { mode: "review_required", days: 60 },
        { mode: "review_required", days: 60 }
      )
    ).toBe(true);
    expect(
      flowRunRetentionPoliciesEqual(
        { mode: "preserve", days: 60 },
        { mode: "review_required", days: 60 }
      )
    ).toBe(false);
    expect(flowRunRetentionPoliciesEqual(null, null)).toBe(true);
    expect(flowRunRetentionPoliciesEqual(null, { mode: "preserve", days: 60 })).toBe(false);
  });
});
