import { describe, expect, it } from "vitest";
import type { Collection, CrawlRun, EmbeddingModel, Website } from "./knowledge";
import { filterCollections, filterCrawlRuns, filterWebsites } from "./table-controls";

const model = (id: string) =>
  ({
    id,
    name: `Model ${id}`,
    is_deprecated: false,
    open_source: false
  }) as EmbeddingModel;

function website(overrides: Partial<Website> & Pick<Website, "id" | "url">): Website {
  const { id, url, ...rest } = overrides;
  return {
    id,
    url,
    name: null,
    space_id: "space",
    update_interval: "never",
    embedding_model: model("a"),
    latest_crawl: null,
    ...rest
  } as Website;
}

function collection(overrides: Partial<Collection> & Pick<Collection, "id" | "name">): Collection {
  const { id, name, ...rest } = overrides;
  return {
    id,
    name,
    space_id: "space",
    embedding_model: model("a"),
    metadata: { num_info_blobs: 0, size: 0 },
    ...rest
  } as Collection;
}

function crawlRun(overrides: Partial<CrawlRun> & Pick<CrawlRun, "id" | "created_at">): CrawlRun {
  const { id, created_at: createdAt, ...rest } = overrides;
  return {
    id,
    created_at: createdAt,
    finished_at: null,
    status: "complete",
    pages_crawled: 0,
    files_downloaded: 0,
    pages_failed: 0,
    files_failed: 0,
    ...rest
  } as CrawlRun;
}

describe("filterWebsites", () => {
  it("matches website name, url, crawl status and embedding model", () => {
    const websites = [
      website({
        id: "alpha",
        name: "Alpha docs",
        url: "https://alpha.example.com",
        latest_crawl: { id: "run-a", status: "complete" } as CrawlRun
      }),
      website({
        id: "beta",
        url: "https://beta.example.com",
        embedding_model: model("beta"),
        latest_crawl: { id: "run-b", status: "failed" } as CrawlRun
      })
    ];

    expect(filterWebsites(websites, "alpha complete")).toEqual([websites[0]]);
    expect(filterWebsites(websites, "model beta")).toEqual([websites[1]]);
    expect(filterWebsites(websites, " ")).toEqual(websites);
  });
});

describe("filterCollections", () => {
  it("matches collection name and whether it has files", () => {
    const empty = collection({
      id: "empty",
      name: "Empty",
      metadata: { num_info_blobs: 0, size: 0 }
    });
    const full = collection({
      id: "full",
      name: "Policies",
      metadata: { num_info_blobs: 12, size: 0 }
    });

    expect(filterCollections([empty, full], "pol").map((item) => item.id)).toEqual(["full"]);
    expect(filterCollections([empty, full], "empty").map((item) => item.id)).toEqual(["empty"]);
  });
});

describe("filterCrawlRuns", () => {
  it("matches the status and the failure reason", () => {
    const done = crawlRun({ id: "done", created_at: "2024-01-01T10:00:00Z", pages_crawled: 2 });
    const failed = crawlRun({
      id: "failed",
      created_at: "2024-01-03T10:00:00Z",
      status: "failed",
      result_location: "Network error"
    });

    expect(filterCrawlRuns([done, failed], "complete").map((run) => run.id)).toEqual(["done"]);
    expect(filterCrawlRuns([done, failed], "network").map((run) => run.id)).toEqual(["failed"]);
    expect(filterCrawlRuns([done, failed], " ")).toEqual([done, failed]);
  });
});
