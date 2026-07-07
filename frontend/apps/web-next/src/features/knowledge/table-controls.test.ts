import { describe, expect, it } from "vitest";
import type { Collection, CrawlRun, EmbeddingModel, Website } from "./knowledge";
import {
  filterAndSortCollections,
  filterAndSortCrawlRuns,
  filterAndSortWebsites
} from "./table-controls";

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

describe("filterAndSortWebsites", () => {
  it("filters by website name, url, crawl status and embedding model", () => {
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

    expect(filterAndSortWebsites(websites, { query: "alpha complete", sort: "name_asc" })).toEqual([
      websites[0]
    ]);
    expect(filterAndSortWebsites(websites, { query: "model beta", sort: "name_asc" })).toEqual([
      websites[1]
    ]);
  });

  it("sorts by latest crawl timestamp", () => {
    const older = website({
      id: "older",
      url: "https://older.example.com",
      latest_crawl: { id: "older-run", created_at: "2024-01-01T10:00:00Z" } as CrawlRun
    });
    const newer = website({
      id: "newer",
      url: "https://newer.example.com",
      latest_crawl: { id: "newer-run", finished_at: "2024-01-03T10:00:00Z" } as CrawlRun
    });

    expect(
      filterAndSortWebsites([older, newer], { query: "", sort: "latest_crawl_desc" }).map(
        (item) => item.id
      )
    ).toEqual(["newer", "older"]);
  });
});

describe("filterAndSortCollections", () => {
  it("filters by collection name and sorts by file count", () => {
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

    expect(
      filterAndSortCollections([empty, full], { query: "pol", sort: "files_desc" }).map(
        (item) => item.id
      )
    ).toEqual(["full"]);
    expect(
      filterAndSortCollections([empty, full], { query: "", sort: "files_desc" }).map(
        (item) => item.id
      )
    ).toEqual(["full", "empty"]);
  });
});

describe("filterAndSortCrawlRuns", () => {
  it("filters by status and sorts by result count", () => {
    const small = crawlRun({
      id: "small",
      created_at: "2024-01-01T10:00:00Z",
      status: "complete",
      pages_crawled: 2
    });
    const large = crawlRun({
      id: "large",
      created_at: "2024-01-02T10:00:00Z",
      status: "complete",
      pages_crawled: 8,
      files_downloaded: 1
    });
    const failed = crawlRun({
      id: "failed",
      created_at: "2024-01-03T10:00:00Z",
      status: "failed",
      result_location: "Network error"
    });

    expect(
      filterAndSortCrawlRuns([small, large, failed], {
        query: "complete",
        sort: "results_desc"
      }).map((item) => item.id)
    ).toEqual(["large", "small"]);
  });

  it("sorts by completed duration", () => {
    const short = crawlRun({
      id: "short",
      created_at: "2024-01-01T10:00:00Z",
      finished_at: "2024-01-01T10:01:00Z"
    });
    const long = crawlRun({
      id: "long",
      created_at: "2024-01-01T10:00:00Z",
      finished_at: "2024-01-01T10:10:00Z"
    });

    expect(
      filterAndSortCrawlRuns([short, long], { query: "", sort: "duration_desc" }).map(
        (item) => item.id
      )
    ).toEqual(["long", "short"]);
  });
});
