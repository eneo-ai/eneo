import { describe, expect, it } from "vitest";
import type { CrawlRun } from "./knowledge";
import { CRAWL_RUN_COMPARATORS, crawlRunResultCount } from "./knowledge-sort";

function crawlRun(overrides: Partial<CrawlRun> & Pick<CrawlRun, "id">): CrawlRun {
  return {
    created_at: "2024-01-01T10:00:00Z",
    finished_at: null,
    status: "complete",
    pages_crawled: 0,
    files_downloaded: 0,
    pages_failed: 0,
    files_failed: 0,
    ...overrides
  } as CrawlRun;
}

const ids = (runs: CrawlRun[]) => runs.map((run) => run.id);

describe("CRAWL_RUN_COMPARATORS", () => {
  it("sorts by start time, result count and duration (ascending; Astryx reverses)", () => {
    const early = crawlRun({
      id: "early",
      created_at: "2024-01-01T10:00:00Z",
      finished_at: "2024-01-01T10:10:00Z",
      pages_crawled: 8,
      files_downloaded: 1
    });
    const late = crawlRun({
      id: "late",
      created_at: "2024-01-02T10:00:00Z",
      finished_at: "2024-01-02T10:01:00Z",
      pages_crawled: 2
    });

    expect(ids([late, early].sort(CRAWL_RUN_COMPARATORS.started))).toEqual(["early", "late"]);
    expect(ids([early, late].sort(CRAWL_RUN_COMPARATORS.results))).toEqual(["late", "early"]);
    expect(ids([early, late].sort(CRAWL_RUN_COMPARATORS.duration))).toEqual(["late", "early"]);
    expect(crawlRunResultCount(early)).toBe(9);
  });

  it("puts problems first when sorting by status", () => {
    const runs = [
      crawlRun({ id: "done" }),
      crawlRun({ id: "queued", status: "queued" }),
      crawlRun({ id: "running", status: "in progress" }),
      crawlRun({ id: "warnings", pages_failed: 1 }),
      crawlRun({
        id: "skipped",
        status: "failed",
        result_location: "Skipped duplicate crawl: another crawl is running"
      }),
      crawlRun({ id: "failed", status: "failed" })
    ];
    // A skipped crawl stood aside for a running one: not a failure (its label is
    // grey "Hoppad över"), so it sorts with the other neutral states.
    expect(ids(runs.sort(CRAWL_RUN_COMPARATORS.status))).toEqual([
      "failed",
      "warnings",
      "running",
      "queued",
      "skipped",
      "done"
    ]);
  });
});
