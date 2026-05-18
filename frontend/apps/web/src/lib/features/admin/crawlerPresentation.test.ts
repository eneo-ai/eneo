/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import {
  crawlerActiveStatusBadgeClass,
  crawlerFailureStateBadgeClass,
  crawlerResultBadgeClass,
  formatCrawlerDateTime
} from "./crawlerPresentation";

overwriteGetLocale(() => "en");

test("formats absolute datetime in the current locale", () => {
  const output = formatCrawlerDateTime("2026-05-17T19:07:00Z");
  expect(output).toMatch(/2026/);
  expect(output).toMatch(/May/);
});

test("returns undefined for unknown result-label colors", () => {
  expect(crawlerResultBadgeClass("unknown" as never)).toBeUndefined();
});

test("maps each result-label color to a distinct class string", () => {
  const classes = new Set(
    (["orange", "green", "moss", "blue"] as const).map((c) => crawlerResultBadgeClass(c))
  );
  expect(classes.size).toBe(4);
  expect([...classes].every((c) => typeof c === "string" && c.length > 0)).toBe(true);
});

test("maps each active lifecycle state to a class string", () => {
  expect(crawlerActiveStatusBadgeClass("running_with_progress")).toContain("positive");
  expect(crawlerActiveStatusBadgeClass("running_no_progress")).toContain("caution");
  expect(crawlerActiveStatusBadgeClass("terminal")).toContain("muted");
  expect(crawlerActiveStatusBadgeClass("queued")).toContain("accent");
});

test("maps each failure state to a class string", () => {
  expect(crawlerFailureStateBadgeClass("BACKED_OFF")).toContain("caution");
  expect(crawlerFailureStateBadgeClass("AUTO_DISABLED")).toContain("destructive");
});
