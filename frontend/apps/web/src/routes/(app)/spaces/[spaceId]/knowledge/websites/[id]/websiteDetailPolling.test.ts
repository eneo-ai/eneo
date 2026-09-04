import type { CrawlRun, Website } from "@eneo/eneo-js";
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
  test.each(["running", "terminal"] as const)(
    "discovers a new %s run using the bounded latest-run endpoint",
    async (phase) => {
      const website = { id: crypto.randomUUID() } as Website;
      const previous = crawlRun("terminal");
      const latestRun = crawlRun(phase);
      const list = vi.fn().mockResolvedValue([latestRun, previous]);
      const latest = vi.fn().mockResolvedValue(latestRun);
      const eneo = { websites: { crawlRuns: { latest, list } } };
      const result = await pollWebsiteDetail(eneo as never, website, [previous]);
      expect(latest).toHaveBeenCalledWith(website);
      expect(list).not.toHaveBeenCalled();
      expect(result).toEqual({ crawlRuns: [previous, latestRun], latestRun });

      await pollWebsiteDetail(eneo as never, website, result.crawlRuns);
      expect(list).not.toHaveBeenCalled();
    }
  );

  test("publishes a known run's terminal status without fetching history or indexed content", async () => {
    const website = { id: crypto.randomUUID() } as Website;
    const running = crawlRun("running");
    const terminal = { ...crawlRun("terminal"), id: running.id };
    const list = vi.fn();
    const eneo = { websites: { crawlRuns: { latest: vi.fn().mockResolvedValue(terminal), list } } };
    expect(await pollWebsiteDetail(eneo as never, website, [running])).toEqual({
      crawlRuns: [terminal],
      latestRun: terminal
    });
    expect(list).not.toHaveBeenCalled();
  });

  test("an idle website without any runs makes only a latest-run request", async () => {
    const website = { id: crypto.randomUUID() } as Website;
    const list = vi.fn();
    const eneo = { websites: { crawlRuns: { latest: vi.fn().mockResolvedValue(null), list } } };
    expect(await pollWebsiteDetail(eneo as never, website, [])).toEqual({
      crawlRuns: [],
      latestRun: null
    });
    expect(list).not.toHaveBeenCalled();
  });
});
