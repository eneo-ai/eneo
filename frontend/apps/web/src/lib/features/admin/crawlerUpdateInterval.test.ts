import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import {
  CRAWLER_UPDATE_INTERVAL_OPTIONS,
  getCrawlerUpdateIntervalLabel,
  isPausingTransition,
  isResumingTransition
} from "./crawlerUpdateInterval";

overwriteGetLocale(() => "en");

test("crawler update interval options expose all backend variants", () => {
  expect(CRAWLER_UPDATE_INTERVAL_OPTIONS).toEqual(["never", "daily", "every_other_day", "weekly"]);
});

test("update interval labels match scheduled-card vocabulary", () => {
  expect(getCrawlerUpdateIntervalLabel("never")).toBe("Manual only");
  expect(getCrawlerUpdateIntervalLabel("daily")).toBe("Daily");
  expect(getCrawlerUpdateIntervalLabel("every_other_day")).toBe("Every other day");
  expect(getCrawlerUpdateIntervalLabel("weekly")).toBe("Weekly");
});

test("pausing transition is true only when leaving a recurring schedule for never", () => {
  expect(isPausingTransition("daily", "never")).toBe(true);
  expect(isPausingTransition("weekly", "never")).toBe(true);
  expect(isPausingTransition("never", "daily")).toBe(false);
  expect(isPausingTransition("never", "never")).toBe(false);
});

test("resuming transition is true only when leaving never for a recurring schedule", () => {
  expect(isResumingTransition("never", "daily")).toBe(true);
  expect(isResumingTransition("never", "weekly")).toBe(true);
  expect(isResumingTransition("daily", "weekly")).toBe(false);
  expect(isResumingTransition("never", "never")).toBe(false);
});
