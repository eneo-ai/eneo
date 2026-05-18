/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import {
  createCrawlerRelativeTimeFormatter,
  formatCrawlerRelativeTime
} from "./crawlerRelativeTime";

overwriteGetLocale(() => "en");

const NOW_ISO = "2026-05-17T19:07:00Z";
const NOW = new Date(NOW_ISO).getTime();
const fmt = createCrawlerRelativeTimeFormatter();

function isoOffset(deltaMs: number): string {
  return new Date(NOW + deltaMs).toISOString();
}

test("relative time returns null for null/empty/invalid input", () => {
  expect(formatCrawlerRelativeTime(fmt, null, NOW)).toBeNull();
  expect(formatCrawlerRelativeTime(fmt, "", NOW)).toBeNull();
  expect(formatCrawlerRelativeTime(fmt, "not-a-date", NOW)).toBeNull();
});

test("relative time renders 'now' when target === now (numeric: auto)", () => {
  expect(formatCrawlerRelativeTime(fmt, NOW_ISO, NOW)).toBe("now");
});

test("relative time renders past seconds inside the 1-minute window", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-30_000), NOW)).toBe("30 seconds ago");
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-59_000), NOW)).toBe("59 seconds ago");
});

test("relative time crosses the 1-minute boundary cleanly", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-60_000), NOW)).toBe("1 minute ago");
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-61_000), NOW)).toBe("1 minute ago");
});

test("relative time renders past minutes inside the 1-hour window", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-5 * 60_000), NOW)).toBe("5 minutes ago");
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-59 * 60_000), NOW)).toBe("59 minutes ago");
});

test("relative time crosses the 1-hour boundary cleanly", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-60 * 60_000), NOW)).toBe("1 hour ago");
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-2 * 60 * 60_000), NOW)).toBe("2 hours ago");
});

test("relative time crosses the 1-day boundary using 'auto' wording", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-23 * 60 * 60_000), NOW)).toBe("23 hours ago");
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-24 * 60 * 60_000), NOW)).toBe("yesterday");
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-3 * 24 * 60 * 60_000), NOW)).toBe("3 days ago");
});

test("relative time renders months inside the 1-year window", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-60 * 24 * 60 * 60_000), NOW)).toBe(
    "2 months ago"
  );
});

test("relative time renders years past the 1-year boundary", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(-2 * 365 * 24 * 60 * 60_000), NOW)).toBe(
    "2 years ago"
  );
});

test("relative time renders future seconds and 'tomorrow' via auto", () => {
  expect(formatCrawlerRelativeTime(fmt, isoOffset(30_000), NOW)).toBe("in 30 seconds");
  expect(formatCrawlerRelativeTime(fmt, isoOffset(24 * 60 * 60_000), NOW)).toBe("tomorrow");
});

test("relative time defaults to Date.now() when 'now' is omitted", () => {
  const recent = new Date(Date.now() - 5_000).toISOString();
  const output = formatCrawlerRelativeTime(fmt, recent);
  expect(output).not.toBeNull();
  expect(output).toMatch(/seconds? ago|now/);
});
