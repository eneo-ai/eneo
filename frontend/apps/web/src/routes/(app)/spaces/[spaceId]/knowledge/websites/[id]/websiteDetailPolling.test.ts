import type { CrawlRun, Website, WebsiteInfoBlobPage } from "@eneo/eneo-js";
import { describe, expect, test, vi } from "vitest";
import { pollWebsiteDetail } from "./websiteDetailPolling";

function crawlRun(phase: CrawlRun["phase"]): CrawlRun {
  return {
    id: crypto.randomUUID(),
    pages_crawled: phase === "terminal" ? 12 : null,
    files_downloaded: null,
    pages_failed: null,
    files_failed: null,
    status: phase === "terminal" ? "complete" : "in progress",
    phase,
    outcome: phase === "terminal" ? "succeeded" : null,
    origin: "manual",
    result_location: null,
    finished_at: null,
    failure_code: null,
    failure_detail: null,
    cancel_requested_at: null,
    attempt_count: 1
  };
}

describe("website detail polling", () => {
  test("refreshes one bounded indexed-content page when a crawl becomes terminal", async () => {
    const website = { id: crypto.randomUUID() } as Website;
    const running = crawlRun("running");
    const terminal = crawlRun("terminal");
    const infoBlobPage = {
      items: [{ id: crypto.randomUUID() }],
      count: 1,
      limit: 100,
      total_count: 1,
      next_cursor: null,
      previous_cursor: null
    } as WebsiteInfoBlobPage;
    const listCrawlRuns = vi.fn().mockResolvedValue([terminal]);
    const listInfoBlobs = vi.fn().mockResolvedValue(infoBlobPage);
    const eneo = {
      websites: {
        crawlRuns: { list: listCrawlRuns },
        indexedBlobs: { list: listInfoBlobs }
      }
    };

    const result = await pollWebsiteDetail(eneo as never, website, [running]);

    expect(listCrawlRuns).toHaveBeenCalledWith(website);
    expect(listInfoBlobs).toHaveBeenCalledWith({ id: website.id, limit: 100 });
    expect(result).toEqual({ crawlRuns: [terminal], infoBlobPage });
  });

  test("does not reload indexed content while the crawl remains active", async () => {
    const website = { id: crypto.randomUUID() } as Website;
    const running = crawlRun("running");
    const listInfoBlobs = vi.fn();
    const eneo = {
      websites: {
        crawlRuns: { list: vi.fn().mockResolvedValue([running]) },
        indexedBlobs: { list: listInfoBlobs }
      }
    };

    const result = await pollWebsiteDetail(eneo as never, website, [running]);

    expect(listInfoBlobs).not.toHaveBeenCalled();
    expect(result).toEqual({ crawlRuns: [running] });
  });
});
