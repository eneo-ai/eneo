import { describe, expect, it } from "vitest";

import {
  flowRunRetentionChangePostponesDeletion,
  flowRunRetentionPoliciesEqual,
  parseFlowRunRetentionDays
} from "./flowRunRetentionPolicy";

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

  it("checks run-history days against the deployment maximum it is given", () => {
    expect(parseFlowRunRetentionDays("36500", 36500)).toBe(36500);
    expect(parseFlowRunRetentionDays("36501", 36500)).toBeNull();
    expect(parseFlowRunRetentionDays("101", 100)).toBeNull();
  });

  it("asks for a reason only when automatic deletion stops or gets later", () => {
    const auto = (days: number) => ({ mode: "auto_delete" as const, days });
    expect(flowRunRetentionChangePostponesDeletion(auto(30), null)).toBe(true);
    expect(flowRunRetentionChangePostponesDeletion(auto(30), { mode: "preserve", days: 30 })).toBe(
      true
    );
    expect(flowRunRetentionChangePostponesDeletion(auto(30), auto(31))).toBe(true);
    expect(flowRunRetentionChangePostponesDeletion(auto(30), auto(30))).toBe(false);
    expect(flowRunRetentionChangePostponesDeletion(auto(30), auto(10))).toBe(false);
    expect(flowRunRetentionChangePostponesDeletion(null, auto(10))).toBe(false);
    expect(flowRunRetentionChangePostponesDeletion({ mode: "preserve", days: 30 }, null)).toBe(
      false
    );
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
