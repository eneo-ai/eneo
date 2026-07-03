import { describe, it, expect } from "vitest";
import {
  isFlowRetentionDays,
  parseFlowRetentionDaysInput,
  FLOW_RETENTION_MIN_DAYS,
  FLOW_RETENTION_MAX_DAYS
} from "./flowEditorRetention";

describe("isFlowRetentionDays", () => {
  it("accepts integers within the retention range", () => {
    expect(isFlowRetentionDays(FLOW_RETENTION_MIN_DAYS)).toBe(true);
    expect(isFlowRetentionDays(FLOW_RETENTION_MAX_DAYS)).toBe(true);
    expect(isFlowRetentionDays(30)).toBe(true);
  });

  it("rejects out-of-range or non-integer values", () => {
    expect(isFlowRetentionDays(0)).toBe(false);
    expect(isFlowRetentionDays(FLOW_RETENTION_MAX_DAYS + 1)).toBe(false);
    expect(isFlowRetentionDays(1.5)).toBe(false);
  });
});

describe("parseFlowRetentionDaysInput", () => {
  it("maps empty input to null (no limit)", () => {
    expect(parseFlowRetentionDaysInput("")).toBeNull();
    expect(parseFlowRetentionDaysInput("   ")).toBeNull();
  });

  it("parses a bare positive integer", () => {
    expect(parseFlowRetentionDaysInput("90")).toBe(90);
    expect(parseFlowRetentionDaysInput(" 90 ")).toBe(90);
  });

  it("rejects non-integer input as undefined", () => {
    expect(parseFlowRetentionDaysInput("90d")).toBeUndefined();
    expect(parseFlowRetentionDaysInput("-1")).toBeUndefined();
    expect(parseFlowRetentionDaysInput("1.5")).toBeUndefined();
  });
});
