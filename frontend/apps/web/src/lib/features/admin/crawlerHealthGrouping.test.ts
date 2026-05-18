/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
 * See the LICENSE file at the repository root for the full license text.
 */

import { expect, test } from "vitest";

import { groupCrawlerHealthRows } from "./crawlerHealthGrouping";

type Row = {
  readonly website_id: string;
  readonly outcome: string;
  readonly finished_at: string;
};

const outcomeKey = (row: Row): string => row.outcome;

test("groups empty input as empty array", () => {
  expect(groupCrawlerHealthRows<Row>([], outcomeKey)).toEqual([]);
});

test("groups a single item as one group with count 1", () => {
  const row: Row = {
    website_id: "w-1",
    outcome: "timeout",
    finished_at: "2026-05-17T10:00:00Z"
  };
  const groups = groupCrawlerHealthRows([row], outcomeKey);
  expect(groups).toHaveLength(1);
  expect(groups[0]).toMatchObject({
    representative: row,
    count: 1,
    firstFinishedAt: row.finished_at,
    latestFinishedAt: row.finished_at
  });
});

test("merges identical (website_id, outcome) rows into one group", () => {
  const rows: Row[] = [
    { website_id: "w-1", outcome: "timeout", finished_at: "2026-05-17T08:00:00Z" },
    { website_id: "w-1", outcome: "timeout", finished_at: "2026-05-17T10:00:00Z" },
    { website_id: "w-1", outcome: "timeout", finished_at: "2026-05-17T09:00:00Z" }
  ];
  const groups = groupCrawlerHealthRows(rows, outcomeKey);
  expect(groups).toHaveLength(1);
  expect(groups[0].count).toBe(3);
  expect(groups[0].firstFinishedAt).toBe("2026-05-17T08:00:00Z");
  expect(groups[0].latestFinishedAt).toBe("2026-05-17T10:00:00Z");
});

test("keeps distinct rows with different outcomes separate", () => {
  const rows: Row[] = [
    { website_id: "w-1", outcome: "timeout", finished_at: "2026-05-17T08:00:00Z" },
    { website_id: "w-1", outcome: "http_500", finished_at: "2026-05-17T09:00:00Z" }
  ];
  const groups = groupCrawlerHealthRows(rows, outcomeKey);
  expect(groups).toHaveLength(2);
});

test("keeps distinct rows with different website_id separate", () => {
  const rows: Row[] = [
    { website_id: "w-1", outcome: "timeout", finished_at: "2026-05-17T08:00:00Z" },
    { website_id: "w-2", outcome: "timeout", finished_at: "2026-05-17T09:00:00Z" }
  ];
  const groups = groupCrawlerHealthRows(rows, outcomeKey);
  expect(groups).toHaveLength(2);
});

test("sorts groups by latestFinishedAt descending", () => {
  const rows: Row[] = [
    { website_id: "older", outcome: "timeout", finished_at: "2026-05-15T00:00:00Z" },
    { website_id: "newest", outcome: "timeout", finished_at: "2026-05-17T00:00:00Z" },
    { website_id: "middle", outcome: "timeout", finished_at: "2026-05-16T00:00:00Z" }
  ];
  const groups = groupCrawlerHealthRows(rows, outcomeKey);
  expect(groups.map((g) => g.representative.website_id)).toEqual(["newest", "middle", "older"]);
});

test("uses the latest item in the group as the representative", () => {
  const rows: Row[] = [
    { website_id: "w-1", outcome: "timeout", finished_at: "2026-05-17T08:00:00Z" },
    { website_id: "w-1", outcome: "timeout", finished_at: "2026-05-17T10:00:00Z" }
  ];
  const groups = groupCrawlerHealthRows(rows, outcomeKey);
  expect(groups[0].representative.finished_at).toBe("2026-05-17T10:00:00Z");
});
