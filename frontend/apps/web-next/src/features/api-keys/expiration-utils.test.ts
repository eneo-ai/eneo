import { afterEach, describe, expect, it, vi } from "vitest";
import { getDaysUntilExpiration, summaryToDisplayItems } from "./expiration-utils";

describe("getDaysUntilExpiration", () => {
  afterEach(() => vi.useRealTimers());

  it("uses whole UTC days until expiration", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T12:00:00Z"));

    expect(getDaysUntilExpiration("2026-01-03T12:00:00Z")).toBe(2);
    expect(getDaysUntilExpiration("2026-01-01T18:00:00Z")).toBe(0);
    expect(getDaysUntilExpiration("2025-12-31T12:00:00Z")).toBe(-1);
  });
});

describe("summaryToDisplayItems", () => {
  afterEach(() => vi.useRealTimers());

  it("normalizes endpoint summary items for notification display", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));

    expect(
      summaryToDisplayItems([
        {
          id: "key-1",
          name: "Production",
          key_suffix: "abcd",
          scope_type: "tenant",
          scope_id: null,
          expires_at: "2026-01-02T00:00:00Z",
          suspended_at: "2025-12-01T00:00:00Z",
          severity: "urgent"
        }
      ])
    ).toEqual([
      {
        id: "key-1",
        name: "Production",
        keySuffix: "abcd",
        daysRemaining: 1,
        level: "urgent",
        suspended: true
      }
    ]);
  });
});
