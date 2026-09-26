import { describe, expect, it } from "vitest";
import { makeWebsite } from "@/features/spaces/testing/space-fixture";
import type { CrawlRun, Website } from "./knowledge";
import { websiteComparators } from "./knowledge-sort";
import {
  crawlFailuresText,
  nextCrawlAt,
  pagesAndFilesText,
  websiteSyncedAt
} from "./website-status";

const website = (latestCrawl: Partial<CrawlRun> | null, overrides: Record<string, unknown> = {}) =>
  makeWebsite({
    latest_crawl: latestCrawl && {
      ...(makeWebsite().latest_crawl as Record<string, unknown>),
      ...latestCrawl
    },
    ...overrides
  }) as unknown as Website;

// ICU-style stand-in for next-intl: enough to see which forms are chosen.
const t = (key: string, values: Record<string, string | number> = {}) =>
  `${key}(${Object.entries(values)
    .map(([name, value]) => `${name}=${value}`)
    .join(",")})`;

describe("websiteSyncedAt", () => {
  it("is when the latest crawl completed, and unknown while one runs or after a failure", () => {
    expect(websiteSyncedAt(website({ finished_at: "2026-09-10T09:00:00Z" }))).toBe(
      "2026-09-10T09:00:00Z"
    );
    expect(websiteSyncedAt(website({ status: "in progress", finished_at: null }))).toBeNull();
    expect(websiteSyncedAt(website({ status: "queued", finished_at: null }))).toBeNull();
    expect(websiteSyncedAt(website({ status: "failed" }))).toBeNull();
    expect(websiteSyncedAt(website(null))).toBeNull();
  });

  it("sorts websites that never synced first when sorting by last sync", () => {
    const compare = websiteComparators((a, b) => a.localeCompare(b)).synced;
    const synced = website({ finished_at: "2026-09-10T09:00:00Z" }, { id: "synced" });
    const running = website({ status: "in progress", finished_at: null }, { id: "running" });
    expect([synced, running].sort(compare).map((item) => item.id)).toEqual(["running", "synced"]);
  });
});

describe("nextCrawlAt", () => {
  it("adds the interval to the latest crawl, after the first one, and only when automatic", () => {
    expect(
      nextCrawlAt(website({ finished_at: "2026-09-10T09:00:00Z" }, { update_interval: "weekly" }))
    ).toBe("2026-09-17T09:00:00.000Z");
    expect(
      nextCrawlAt(website({ finished_at: "2026-09-10T09:00:00Z" }, { update_interval: "daily" }))
    ).toBe("2026-09-11T09:00:00.000Z");
    expect(nextCrawlAt(website(null, { update_interval: "weekly" }))).toBeNull();
    expect(nextCrawlAt(website({}, { update_interval: "never" }))).toBeUndefined();
  });
});

describe("pagesAndFilesText", () => {
  it("names the kinds that occurred, each with its own plural form", () => {
    expect(pagesAndFilesText(t, 3, 0)).toBe("space_pages_count(count=3)");
    expect(pagesAndFilesText(t, 0, 1)).toBe("space_files_count(count=1)");
    expect(pagesAndFilesText(t, 0, 0)).toBe("space_pages_count(count=0)");
    expect(pagesAndFilesText(t, 2, 1)).toBe(
      "space_pages_and_files(pages=space_pages_count(count=2),files=space_files_count(count=1))"
    );
  });

  it("says what failed in a crawl with warnings", () => {
    expect(crawlFailuresText(t, { pages_failed: 1, files_failed: 0 } as CrawlRun)).toBe(
      "space_crawl_failed(items=space_pages_count(count=1))"
    );
    expect(crawlFailuresText(t, { pages_failed: 0, files_failed: 0 } as CrawlRun)).toBeUndefined();
  });
});
