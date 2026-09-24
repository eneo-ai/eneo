import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import { ACTIVITY_RANK, activityLabel } from "./activity";

const buckets = ["past_week", "past_month", "past_quarter", "older", "none"] as const;

describe("space activity", () => {
  it("labels every bucket with its own message", () => {
    expect(buckets.map(activityLabel)).toEqual([
      "admin_spaces_activity_past_week",
      "admin_spaces_activity_past_month",
      "admin_spaces_activity_past_quarter",
      "admin_spaces_activity_older",
      "admin_spaces_activity_none"
    ]);
  });

  it("ranks the most recent bucket highest and no activity lowest", () => {
    const ranks = buckets.map((bucket) => ACTIVITY_RANK[bucket]);
    expect(ranks).toEqual([...ranks].sort((a, b) => b - a));
    expect(new Set(ranks).size).toBe(buckets.length);
    expect(ACTIVITY_RANK.none).toBe(Math.min(...ranks));
  });

  it("shows a bucket this build does not know as it came", () => {
    expect(activityLabel("yesterday" as never)).toBe("yesterday");
  });
});
