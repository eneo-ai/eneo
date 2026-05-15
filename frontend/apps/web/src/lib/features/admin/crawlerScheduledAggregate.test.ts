import { expect, test } from "vitest";
import { overwriteGetLocale } from "$lib/paraglide/runtime";

import type { CrawlerScheduledAggregateResponse } from "./crawlerScheduledAggregate";
import {
  formatCrawlerScheduledCount,
  formatCrawlerScheduledIndexedSize,
  getCrawlerScheduledAggregateTotalLabel,
  getCrawlerScheduledIntervalLabel,
  getCrawlerScheduledUnparseableLabel
} from "./crawlerScheduledAggregate";

overwriteGetLocale(() => "en");

const scheduledAggregate: CrawlerScheduledAggregateResponse = {
  buckets: [
    {
      update_interval: "daily",
      website_count: 2,
      total_size_bytes: 2_097_152
    },
    {
      update_interval: "every_other_day",
      website_count: 0,
      total_size_bytes: 0
    },
    {
      update_interval: "never",
      website_count: 1,
      total_size_bytes: 500
    },
    {
      update_interval: "weekly",
      website_count: 3,
      total_size_bytes: 1_536
    }
  ],
  total_websites: 7,
  total_size_bytes: 2_099_188,
  unparseable_update_interval_website_count: 1,
  unparseable_update_interval_total_size_bytes: 1_000,
  tenant_id: "33333333-3333-4333-8333-333333333333"
};

test("scheduled aggregate labels use stable interval names and readable totals", () => {
  expect(getCrawlerScheduledIntervalLabel("daily")).toBe("Daily");
  expect(getCrawlerScheduledIntervalLabel("every_other_day")).toBe("Every other day");
  expect(getCrawlerScheduledIntervalLabel("weekly")).toBe("Weekly");
  expect(getCrawlerScheduledIntervalLabel("never")).toBe("Manual only");
  expect(getCrawlerScheduledAggregateTotalLabel(scheduledAggregate)).toBe(
    "Websites scheduled: 7 · Indexed: 2 MiB"
  );
  expect(
    getCrawlerScheduledAggregateTotalLabel({
      ...scheduledAggregate,
      total_websites: 1
    })
  ).toBe("Websites scheduled: 1 · Indexed: 2 MiB");
});

test("scheduled aggregate surfaces unparseable legacy interval counts", () => {
  expect(getCrawlerScheduledUnparseableLabel(scheduledAggregate)).toBe(
    "Websites with legacy update intervals: 1"
  );
  expect(
    getCrawlerScheduledUnparseableLabel({
      ...scheduledAggregate,
      unparseable_update_interval_website_count: 2
    })
  ).toBe("Websites with legacy update intervals: 2");
  expect(
    getCrawlerScheduledUnparseableLabel({
      ...scheduledAggregate,
      unparseable_update_interval_website_count: 0,
      unparseable_update_interval_total_size_bytes: 0
    })
  ).toBeNull();
});

test("scheduled aggregate size formatting stays compact", () => {
  expect(formatCrawlerScheduledIndexedSize(500)).toBe("500 B");
  expect(formatCrawlerScheduledIndexedSize(1023)).toBe("1,023 B");
  expect(formatCrawlerScheduledIndexedSize(1024)).toBe("1 KiB");
  expect(formatCrawlerScheduledIndexedSize(1_536)).toBe("1.5 KiB");
  expect(formatCrawlerScheduledIndexedSize(2_097_152)).toBe("2 MiB");
  expect(formatCrawlerScheduledIndexedSize(5 * 1024 * 1024 * 1024)).toBe("5 GiB");
  expect(formatCrawlerScheduledIndexedSize(2 * 1024 * 1024 * 1024 * 1024)).toBe("2 TiB");
});

test("scheduled aggregate count formatting stays locale-aware", () => {
  expect(formatCrawlerScheduledCount(1_234)).toBe("1,234");
  expect(formatCrawlerScheduledCount(-1)).toBe("0");
});
