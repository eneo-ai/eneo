import { describe, expect, it } from "vitest";
import { KEY_EXPIRY_WARNING_DAYS, keyExpiry, localIsoDate } from "./key-expiry";

describe("keyExpiry", () => {
  const today = "2026-09-26";

  it("says nothing without a date or before the warning window", () => {
    expect(keyExpiry(null, today)).toBeNull();
    expect(keyExpiry(undefined, today)).toBeNull();
    expect(keyExpiry("2026-10-27", today)).toBeNull();
  });

  it(`warns from ${KEY_EXPIRY_WARNING_DAYS} days before through the expiry day`, () => {
    expect(keyExpiry("2026-10-26", today)).toEqual({ state: "expiring", date: "2026-10-26" });
    expect(keyExpiry("2026-09-26", today)).toEqual({ state: "expiring", date: "2026-09-26" });
  });

  it("has expired from the day after", () => {
    expect(keyExpiry("2026-09-25", today)).toEqual({ state: "expired", date: "2026-09-25" });
    expect(keyExpiry("2025-01-01", today)).toEqual({ state: "expired", date: "2025-01-01" });
  });

  it("counts calendar days across a daylight saving change", () => {
    // Sweden leaves summer time on 25 October 2026.
    expect(keyExpiry("2026-11-24", "2026-10-25")?.state).toBe("expiring");
    expect(keyExpiry("2026-11-25", "2026-10-25")).toBeNull();
  });

  it("ignores a malformed date", () => {
    expect(keyExpiry("snart", today)).toBeNull();
  });
});

describe("localIsoDate", () => {
  it("uses the viewer's calendar date, not UTC", () => {
    expect(localIsoDate(new Date(2026, 0, 5, 0, 30))).toBe("2026-01-05");
    expect(localIsoDate(new Date(2026, 11, 31, 23, 59))).toBe("2026-12-31");
  });
});
