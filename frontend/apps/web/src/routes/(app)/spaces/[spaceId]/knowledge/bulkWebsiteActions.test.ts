import { describe, expect, it, vi } from "vitest";
import {
  bulkDeletionWaitsForCrawlerCleanup,
  bulkFailureWebsiteIds,
  deleteWebsiteBatches,
  runWebsiteBatches,
  stopWebsiteBatches,
  toggleVisibleWebsiteSelection,
  visibleWebsiteIdsFromTableRows
} from "./bulkWebsiteActions";

describe("bulk website actions", () => {
  it("runs large selections in bounded batches and aggregates the result", async () => {
    const websiteIds = Array.from({ length: 121 }, (_, index) => `website-${index}`);
    const runBatch = vi.fn(async (batch: string[]) => ({
      total: batch.length,
      queued: batch.length - 1,
      failed: 1,
      errors: [{ website_id: batch.at(-1) ?? "", error: "not_authorized" as const }]
    }));

    const result = await runWebsiteBatches(websiteIds, runBatch);

    expect(runBatch.mock.calls.map(([batch]) => batch.length)).toEqual([50, 50, 21]);
    expect(result).toEqual({
      total: 121,
      queued: 118,
      failed: 3,
      errors: [
        { website_id: "website-49", error: "not_authorized" },
        { website_id: "website-99", error: "not_authorized" },
        { website_id: "website-120", error: "not_authorized" }
      ]
    });
  });

  it("deduplicates IDs before sending requests", async () => {
    const runBatch = vi.fn(async (batch: string[]) => ({
      total: batch.length,
      queued: batch.length,
      failed: 0,
      errors: []
    }));

    const result = await runWebsiteBatches(["website-1", "website-1", "website-2"], runBatch);

    expect(runBatch).toHaveBeenCalledOnce();
    expect(runBatch).toHaveBeenCalledWith(["website-1", "website-2"]);
    expect(result.total).toBe(2);
  });

  it("treats already-finished crawls as a normal stop result", async () => {
    const stopBatch = vi.fn(async (batch: string[]) => ({
      total: batch.length,
      stopped: 1,
      not_running: batch.length - 1,
      failed: 0,
      errors: []
    }));

    const result = await stopWebsiteBatches(
      ["website-running", "website-finished", "website-stale"],
      stopBatch
    );

    expect(result).toEqual({
      total: 3,
      stopped: 1,
      notRunning: 2,
      failed: 0,
      errors: []
    });
  });

  it("reports the failed and unattempted IDs when a later run batch cannot be sent", async () => {
    const websiteIds = Array.from({ length: 121 }, (_, index) => `website-${index}`);
    const runBatch = vi
      .fn<Parameters<typeof runWebsiteBatches>[1]>()
      .mockImplementationOnce(async (batch) => ({
        total: batch.length,
        queued: batch.length,
        failed: 0,
        errors: []
      }))
      .mockRejectedValueOnce(new Error("network unavailable"));

    const result = await runWebsiteBatches(websiteIds, runBatch);

    expect(runBatch.mock.calls.map(([batch]) => batch.length)).toEqual([50, 50]);
    expect(result.total).toBe(121);
    expect(result.queued).toBe(50);
    expect(result.failed).toBe(71);
    expect(result.errors.map((error) => error.website_id)).toEqual(websiteIds.slice(50));
  });

  it("keeps completed stop results when a later batch cannot be sent", async () => {
    const websiteIds = Array.from({ length: 75 }, (_, index) => `website-${index}`);
    const stopBatch = vi
      .fn<Parameters<typeof stopWebsiteBatches>[1]>()
      .mockImplementationOnce(async (batch) => ({
        total: batch.length,
        stopped: 40,
        not_running: 10,
        failed: 0,
        errors: []
      }))
      .mockRejectedValueOnce(new Error("connection reset"));

    const result = await stopWebsiteBatches(websiteIds, stopBatch);

    expect(result).toMatchObject({ total: 75, stopped: 40, notRunning: 10, failed: 25 });
    expect(result.errors.map((error) => error.website_id)).toEqual(websiteIds.slice(50));
  });

  it("deletes large selections in bounded batches and treats missing sources as normal", async () => {
    const websiteIds = Array.from({ length: 75 }, (_, index) => `website-${index}`);
    const deleteBatch = vi.fn(async (batch: string[]) => ({
      total: batch.length,
      deleted: batch.length - 1,
      not_found: 1,
      failed: 0,
      errors: []
    }));

    const result = await deleteWebsiteBatches(websiteIds, deleteBatch);

    expect(deleteBatch.mock.calls.map(([batch]) => batch.length)).toEqual([50, 25]);
    expect(result).toEqual({
      total: 75,
      deleted: 73,
      notFound: 2,
      failed: 0,
      errors: []
    });
  });

  it("keeps completed deletes and reports all remaining IDs when a later batch fails", async () => {
    const websiteIds = Array.from({ length: 121 }, (_, index) => `website-${index}`);
    const deleteBatch = vi
      .fn<Parameters<typeof deleteWebsiteBatches>[1]>()
      .mockImplementationOnce(async (batch) => ({
        total: batch.length,
        deleted: 48,
        not_found: 2,
        failed: 0,
        errors: []
      }))
      .mockRejectedValueOnce(new Error("network unavailable"));

    const result = await deleteWebsiteBatches(websiteIds, deleteBatch);

    expect(deleteBatch.mock.calls.map(([batch]) => batch.length)).toEqual([50, 50]);
    expect(result).toMatchObject({ total: 121, deleted: 48, notFound: 2, failed: 71 });
    expect(result.errors.map((error) => error.website_id)).toEqual(websiteIds.slice(50));
  });

  it("selects only visible rows while preserving hidden selections", () => {
    const selected = new Set(["hidden", "visible-1"]);

    expect(toggleVisibleWebsiteSelection(selected, ["visible-1", "visible-2"])).toEqual(
      new Set(["hidden", "visible-1", "visible-2"])
    );
  });

  it("projects visible website IDs from row data identity rather than display index", () => {
    const rows = [
      { id: "0", dataId: "website-uuid-1", isData: () => true },
      { id: "1", dataId: "website-uuid-2", isData: () => true }
    ];

    expect(visibleWebsiteIdsFromTableRows(rows)).toEqual(["website-uuid-1", "website-uuid-2"]);
  });

  it("deselects only visible rows when every visible row is selected", () => {
    const selected = new Set(["hidden", "visible-1", "visible-2"]);

    expect(toggleVisibleWebsiteSelection(selected, ["visible-1", "visible-2"])).toEqual(
      new Set(["hidden"])
    );
  });

  it("returns only failed website IDs for retry selection", () => {
    expect(
      bulkFailureWebsiteIds([
        { website_id: "failed-1", error: "crawl_active" },
        { website_id: "failed-2", error: "not_authorized" },
        { website_id: "failed-1", error: "crawl_active" }
      ])
    ).toEqual(["failed-1", "failed-2"]);
  });

  it("recognizes deletion retries that are waiting for crawler cleanup", () => {
    expect(
      bulkDeletionWaitsForCrawlerCleanup([
        { website_id: "stopping", error: "crawl_stop_requested" }
      ])
    ).toBe(true);
    expect(
      bulkDeletionWaitsForCrawlerCleanup([{ website_id: "forbidden", error: "not_authorized" }])
    ).toBe(false);
    expect(
      bulkDeletionWaitsForCrawlerCleanup([
        { website_id: "stopping", error: "crawl_stop_requested" },
        { website_id: "forbidden", error: "not_authorized" }
      ])
    ).toBe(false);
  });
});
