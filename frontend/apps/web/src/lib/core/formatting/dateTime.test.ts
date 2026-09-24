import { afterEach, describe, expect, it, vi } from "vitest";

const locale = vi.hoisted(() => ({ current: "en" }));
vi.mock("$lib/paraglide/runtime", () => ({ getLocale: () => locale.current }));

import {
  formatDate,
  formatDateMedium,
  formatDateTime,
  formatDuration,
  formatRelativeTime,
  formatTime,
  intlLocale
} from "./dateTime";

afterEach(() => {
  locale.current = "en";
});

describe("dateTime", () => {
  it("maps the UI language to an Intl locale", () => {
    expect(intlLocale()).toBe("en-US");
    locale.current = "sv";
    expect(intlLocale()).toBe("sv-SE");
  });

  it("formats dates and times as YYYY-MM-DD HH:mm in local time", () => {
    const date = new Date(2026, 0, 5, 9, 7);
    expect(formatDate(date)).toBe("2026-01-05");
    expect(formatDateTime(date)).toBe("2026-01-05 09:07");
    expect(formatDateTime(date.toISOString())).toBe("2026-01-05 09:07");
  });

  it("formats relative time in the UI language with the largest fitting unit", () => {
    const now = new Date(2026, 8, 23, 12, 0).getTime();
    expect(formatRelativeTime(now - 3 * 60 * 60 * 1000, now)).toBe("3 hours ago");
    expect(formatRelativeTime(now - 24 * 60 * 60 * 1000, now)).toBe("yesterday");
    expect(formatRelativeTime(now - 20 * 1000, now)).toBe("20 seconds ago");
    locale.current = "sv";
    expect(formatRelativeTime(now - 3 * 60 * 60 * 1000, now)).toBe("för 3 timmar sedan");
  });

  it("formats times, with seconds on request, and medium dates in the UI language", () => {
    const date = new Date(2026, 8, 3, 7, 5, 9);
    expect(formatTime(date)).toBe("07:05");
    expect(formatDateTime(date, { seconds: true })).toBe("2026-09-03 07:05:09");
    expect(formatDateMedium(date)).toBe("Sep 3, 2026");
    locale.current = "sv";
    expect(formatDateMedium(date)).toBe("3 sep. 2026");
  });

  it("formats durations in their largest whole unit", () => {
    expect(formatDuration(5 * 60 * 1000 + 20 * 1000)).toBe("5 minutes");
    expect(formatDuration(45 * 1000)).toBe("45 seconds");
    expect(formatDuration(2 * 60 * 60 * 1000)).toBe("2 hours");
    locale.current = "sv";
    expect(formatDuration(5 * 60 * 1000)).toBe("5 minuter");
  });

  it("returns an empty string for unset, empty and invalid values", () => {
    expect(formatDate(null)).toBe("");
    expect(formatDateTime(undefined)).toBe("");
    expect(formatRelativeTime(null)).toBe("");
    expect(formatDateTime("")).toBe("");
    expect(formatDateTime("not a date")).toBe("");
    expect(formatDateMedium("not a date")).toBe("");
    expect(formatRelativeTime("not a date")).toBe("");
  });
});
