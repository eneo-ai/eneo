import { describe, expect, it } from "vitest";
import { makeWebsite } from "@/features/spaces/testing/space-fixture";
import { crawlProgressFrom, endedCrawls, newerCrawlRun, withCrawlProgress } from "./crawl-progress";
import type { CrawlRun, Website } from "./knowledge";

function run(overrides: Partial<CrawlRun> = {}): CrawlRun {
  return {
    id: "run-1",
    phase: "running",
    outcome: null,
    status: "in progress",
    origin: "manual",
    pages_crawled: 10,
    files_downloaded: 0,
    pages_failed: 0,
    files_failed: 0,
    result_location: null,
    finished_at: null,
    failure_code: null,
    failure_detail: null,
    created_at: "2026-10-26T10:00:00Z",
    updated_at: "2026-10-26T10:01:00Z",
    ...overrides
  } as CrawlRun;
}

describe("newerCrawlRun", () => {
  it("keeps the space's run when the poll has none for the website", () => {
    const fromSpace = run();
    expect(newerCrawlRun(fromSpace, undefined)).toBe(fromSpace);
    expect(newerCrawlRun(null, undefined)).toBeNull();
  });

  it("takes the polled progress of the same running crawl", () => {
    const polled = run({ pages_crawled: 40, updated_at: "2026-10-26T10:02:00Z" });
    expect(newerCrawlRun(run(), polled)).toBe(polled);
  });

  it("keeps the space's newer read of the same crawl, and an ended crawl never runs again", () => {
    const later = run({ pages_crawled: 50, updated_at: "2026-10-26T10:03:00Z" });
    expect(newerCrawlRun(later, run())).toBe(later);
    const ended = run({
      phase: "terminal",
      outcome: "succeeded",
      finished_at: "2026-10-26T10:02:00Z"
    });
    expect(newerCrawlRun(ended, run({ updated_at: "2026-10-26T10:05:00Z" }))).toBe(ended);
  });

  it("takes whichever crawl started later when the space and the poll read different ones", () => {
    const earlier = run({ id: "run-1", phase: "terminal", outcome: "succeeded" });
    const next = run({ id: "run-2", created_at: "2026-10-26T11:00:00Z" });
    expect(newerCrawlRun(earlier, next)).toBe(next);
    expect(newerCrawlRun(next, earlier)).toBe(next);
  });

  it("takes the polled crawl for a website the space read before any crawl", () => {
    const polled = run();
    expect(newerCrawlRun(null, polled)).toBe(polled);
  });
});

describe("withCrawlProgress", () => {
  const websites = [
    makeWebsite({ id: "w1", latest_crawl: run({ id: "run-1" }) }),
    makeWebsite({
      id: "w2",
      latest_crawl: run({ id: "run-9", phase: "terminal", outcome: "succeeded" })
    })
  ] as unknown as Website[];

  it("shows the polled progress and keeps every other website as it was", () => {
    const polled = run({ id: "run-1", pages_crawled: 70, updated_at: "2026-10-26T10:04:00Z" });
    const merged = withCrawlProgress(
      websites,
      crawlProgressFrom([{ website_id: "w1", latest_crawl: polled }])
    );
    expect(merged[0]!.latest_crawl).toBe(polled);
    expect(merged[1]).toBe(websites[1]);
  });

  it("returns the same list when the poll adds nothing", () => {
    expect(withCrawlProgress(websites, undefined)).toBe(websites);
    expect(withCrawlProgress(websites, crawlProgressFrom([]))).toBe(websites);
  });
});

describe("endedCrawls", () => {
  const shown = (id: string, crawl: CrawlRun | null) =>
    makeWebsite({ id, latest_crawl: crawl }) as unknown as Website;

  it("names the running crawls the progress no longer has, once each", () => {
    const websites = [
      shown("w1", run({ id: "run-1" })),
      shown(
        "w2",
        run({ id: "run-2", phase: "terminal", outcome: "succeeded", status: "complete" })
      ),
      shown("w3", run({ id: "run-3" })),
      shown("w4", null)
    ];
    const progress = crawlProgressFrom([
      { website_id: "w3", latest_crawl: run({ id: "run-3", pages_crawled: 99 }) }
    ]);
    expect(endedCrawls([...websites, websites[0]!], progress)).toBe("w1:run-1");
  });

  it("counts a crawl another run took the place of as ended", () => {
    const progress = crawlProgressFrom([{ website_id: "w1", latest_crawl: run({ id: "run-9" }) }]);
    expect(endedCrawls([shown("w1", run({ id: "run-1" }))], progress)).toBe("w1:run-1");
    expect(endedCrawls([shown("w1", run({ id: "run-9" }))], progress)).toBe("");
  });
});
