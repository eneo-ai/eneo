import { describe, expect, it, vi } from "vitest";
import {
  bulkDeletionWaitsForCrawlerCleanup,
  bulkFailureWebsiteIds,
  deleteWebsiteBatches,
  MAX_WEBSITES_PER_REQUEST,
  runWebsiteBatches,
  stopWebsiteBatches
} from "./bulk-website-actions";

const ids = (count: number, prefix = "w") =>
  Array.from({ length: count }, (_, index) => `${prefix}-${index + 1}`);

describe("runWebsiteBatches", () => {
  it("sends unique ids in batches of at most 50 and sums the results", async () => {
    const runBatch = vi.fn((websiteIds: string[]) =>
      Promise.resolve({
        total: websiteIds.length,
        queued: websiteIds.length - 1,
        failed: 1,
        crawl_runs: [],
        errors: [{ website_id: websiteIds[0]!, error: "crawl_active" as const }]
      })
    );

    const summary = await runWebsiteBatches([...ids(120), "w-1"], runBatch);

    expect(runBatch).toHaveBeenCalledTimes(3);
    expect(runBatch.mock.calls.map(([batch]) => batch.length)).toEqual([
      MAX_WEBSITES_PER_REQUEST,
      MAX_WEBSITES_PER_REQUEST,
      20
    ]);
    expect(summary).toMatchObject({ total: 120, queued: 117, failed: 3 });
    expect(bulkFailureWebsiteIds(summary.errors)).toEqual(["w-1", "w-51", "w-101"]);
  });

  it("counts the rest as request failures when a request throws, and stops there", async () => {
    const stopBatch = vi
      .fn()
      .mockResolvedValueOnce({
        total: 50,
        stopped: 49,
        not_running: 1,
        failed: 0,
        crawl_runs: [],
        errors: []
      })
      .mockRejectedValueOnce(new Error("offline"));

    const summary = await stopWebsiteBatches(ids(120), stopBatch);

    expect(stopBatch).toHaveBeenCalledTimes(2);
    expect(summary).toMatchObject({ total: 120, stopped: 49, notRunning: 1, failed: 70 });
    expect(summary.errors).toHaveLength(70);
    expect(summary.errors.every((error) => error.error === "request_failed")).toBe(true);
  });
});

describe("deleteWebsiteBatches", () => {
  it("sums deleted and not-found counts", async () => {
    const summary = await deleteWebsiteBatches(ids(3), (websiteIds) =>
      Promise.resolve({
        total: websiteIds.length,
        deleted: 1,
        not_found: 1,
        failed: 1,
        errors: [{ website_id: "w-3", error: "crawl_stop_requested" as const }]
      })
    );
    expect(summary).toMatchObject({ total: 3, deleted: 1, notFound: 1, failed: 1 });
  });
});

describe("bulkDeletionWaitsForCrawlerCleanup", () => {
  it("is true only when every failure is the crawler stopping or cleaning up", () => {
    expect(bulkDeletionWaitsForCrawlerCleanup([])).toBe(false);
    expect(
      bulkDeletionWaitsForCrawlerCleanup([
        { website_id: "a", error: "crawl_stop_requested" },
        { website_id: "b", error: "crawl_cleanup_pending" }
      ])
    ).toBe(true);
    expect(
      bulkDeletionWaitsForCrawlerCleanup([
        { website_id: "a", error: "crawl_stop_requested" },
        { website_id: "b", error: "not_authorized" }
      ])
    ).toBe(false);
  });
});
