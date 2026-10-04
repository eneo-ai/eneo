import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({ m: {} }));

import { addLocalDays, endOfLocalDay, latestReviewDate, localDate } from "./flowRetentionHold";

const DAY = 24 * 60 * 60 * 1000;
let previousTz: string | undefined;

// The server accepts review_by <= now + limit days; the end of the offered day
// must stay inside that, also across the October daylight-saving change.
beforeAll(() => {
  previousTz = process.env.TZ;
  process.env.TZ = "Europe/Stockholm";
});

afterAll(() => {
  process.env.TZ = previousTz;
});

function expectLatest(now: Date, days: number) {
  const latest = latestReviewDate(now, days);
  const limit = now.getTime() + days * DAY;
  expect(Date.parse(endOfLocalDay(latest))).toBeLessThanOrEqual(limit);
  expect(Date.parse(endOfLocalDay(addLocalDays(latest, 1)))).toBeGreaterThan(limit);
  return latest;
}

describe("latest review date", () => {
  it("is the last whole day inside the limit on an ordinary day", () => {
    const now = new Date(2026, 5, 10, 14, 0);
    expect(expectLatest(now, 30)).toBe(addLocalDays(localDate(now), 29));
  });

  it("does not offer a day the server rejects when the clocks go back in the window", () => {
    // 00:30 local on 5 October; summer time ends on 25 October.
    const now = new Date(2026, 9, 5, 0, 30);
    expect(now.toISOString()).toBe("2026-10-04T22:30:00.000Z");
    expect(expectLatest(now, 30)).toBe("2026-11-02");
  });

  it("offers one more day after the first hour of the night", () => {
    const now = new Date(2026, 9, 5, 1, 30);
    expect(expectLatest(now, 30)).toBe("2026-11-03");
  });

  it("covers the spring change too", () => {
    expectLatest(new Date(2026, 2, 1, 0, 30), 60);
    expectLatest(new Date(2026, 2, 1, 23, 30), 60);
  });
});
