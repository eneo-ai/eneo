/**
 * V2-F: pure-function regression tests for the Webbplatser bulk
 * interval-change toolbar + dialog. The vitest config in this repo
 * only includes `*.{test,spec}.{js,ts}` files (no DOM mount harness
 * for .svelte), so the cap rule, the failed-preview chunking, and
 * the submit-bounds gate are all extracted as pure helpers the
 * dialog consumes — each one is a single source of truth this file
 * exercises directly.
 */

import { describe, it, expect } from "vitest";
import type { components } from "@intric/intric-js";
import {
  CRAWLER_BULK_INTERVAL_FAILED_PREVIEW_LIMIT,
  CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS,
  canSubmitCrawlerBulkIntervalSelection,
  getCrawlerBulkIntervalFailedPreview,
  getCrawlerBulkIntervalFailureLabel,
  getCrawlerBulkIntervalSummaryLabel
} from "./crawlerBulkInterval";

type Response = components["schemas"]["CrawlerBulkIntervalResponse"];
type FailedRow = Response["failed"][number];

const buildFailedRow = (id: string): FailedRow => ({
  website_id: id,
  code: "NOT_FOUND"
});

const buildResponse = (overrides: Partial<Response> = {}): Response => ({
  applied: [],
  unchanged: [],
  failed: [],
  ...overrides
});

describe("canSubmitCrawlerBulkIntervalSelection", () => {
  it("rejects an empty selection", () => {
    expect(canSubmitCrawlerBulkIntervalSelection({ selected_count: 0, interval: "never" })).toBe(
      false
    );
  });

  it("rejects when no interval is picked", () => {
    expect(canSubmitCrawlerBulkIntervalSelection({ selected_count: 5, interval: null })).toBe(
      false
    );
  });

  it("rejects when the cap is exceeded", () => {
    expect(
      canSubmitCrawlerBulkIntervalSelection({
        selected_count: CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS + 1,
        interval: "weekly"
      })
    ).toBe(false);
  });

  it("accepts a non-empty selection at the cap", () => {
    expect(
      canSubmitCrawlerBulkIntervalSelection({
        selected_count: CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS,
        interval: "weekly"
      })
    ).toBe(true);
  });

  it("accepts a typical mid-range selection", () => {
    expect(canSubmitCrawlerBulkIntervalSelection({ selected_count: 5, interval: "daily" })).toBe(
      true
    );
  });
});

describe("getCrawlerBulkIntervalFailedPreview", () => {
  it("returns null when there are no failures", () => {
    expect(getCrawlerBulkIntervalFailedPreview([])).toBeNull();
  });

  it("renders the whole list when at or below the limit", () => {
    const rows = Array.from({ length: CRAWLER_BULK_INTERVAL_FAILED_PREVIEW_LIMIT }).map(
      (_unused, idx) => buildFailedRow(`id-${idx}`)
    );
    const preview = getCrawlerBulkIntervalFailedPreview(rows);
    expect(preview).not.toBeNull();
    expect(preview!.rendered).toHaveLength(rows.length);
    expect(preview!.remaining).toBe(0);
  });

  it("caps the rendered list and reports the remainder", () => {
    const overflow = 3;
    const rows = Array.from({
      length: CRAWLER_BULK_INTERVAL_FAILED_PREVIEW_LIMIT + overflow
    }).map((_unused, idx) => buildFailedRow(`id-${idx}`));
    const preview = getCrawlerBulkIntervalFailedPreview(rows);
    expect(preview).not.toBeNull();
    expect(preview!.rendered).toHaveLength(CRAWLER_BULK_INTERVAL_FAILED_PREVIEW_LIMIT);
    expect(preview!.remaining).toBe(overflow);
  });
});

describe("getCrawlerBulkIntervalSummaryLabel", () => {
  it("renders all three counters even when zero", () => {
    const label = getCrawlerBulkIntervalSummaryLabel(buildResponse());
    expect(label).toContain("0");
  });

  it("uses the response counts directly", () => {
    const response = buildResponse({
      applied: [
        {
          website_id: "a",
          website_name: "Bulk A",
          previous_update_interval: "daily",
          new_update_interval: "weekly",
          failure_state_cleared: false
        }
      ],
      unchanged: [
        {
          website_id: "b",
          website_name: "Bulk B",
          update_interval: "weekly"
        }
      ],
      failed: [buildFailedRow("c")]
    });
    const label = getCrawlerBulkIntervalSummaryLabel(response);
    expect(label).toContain("1");
  });
});

describe("getCrawlerBulkIntervalFailureLabel", () => {
  it("returns a localised label for NOT_FOUND", () => {
    expect(getCrawlerBulkIntervalFailureLabel("NOT_FOUND")).toBeTruthy();
  });
});
