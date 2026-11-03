import { afterEach, describe, expect, it, vi } from "vitest";
import { formatCalendarDate } from "./calendar-date";

afterEach(() => vi.unstubAllEnvs());

describe("formatCalendarDate", () => {
  it.each(["America/Los_Angeles", "Pacific/Kiritimati"])(
    "shows the calendar day itself in %s",
    (zone) => {
      vi.stubEnv("TZ", zone);
      // The zone is in effect: hours away from UTC.
      expect(Math.abs(new Date("2026-03-01T00:00:00Z").getTimezoneOffset())).toBeGreaterThan(400);

      expect(formatCalendarDate("2026-03-01", "en-GB", { day: "numeric", month: "long" })).toBe(
        "1 March"
      );
      expect(formatCalendarDate("2026-03-01", "sv", { dateStyle: "long" })).toBe("1 mars 2026");
    }
  );

  it("gives an invalid date back as it is", () => {
    expect(formatCalendarDate("2026-02-30", "sv", { dateStyle: "long" })).toBe("2026-02-30");
  });
});
