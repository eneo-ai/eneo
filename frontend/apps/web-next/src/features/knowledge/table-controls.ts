import { matchesSearch, type SearchValue } from "@/features/spaces/resource-filter";
import { formatWebsiteName, type Collection, type CrawlRun, type Website } from "./knowledge";

/**
 * Search predicates for the knowledge tables. Collections and websites sort
 * by their column headers (Astryx Table's sortable plugin); crawl runs keep a
 * sort select.
 */

function websiteSearchValues(website: Website): SearchValue[] {
  const crawl = website.latest_crawl;
  return [
    formatWebsiteName(website),
    website.url,
    website.name,
    website.update_interval,
    website.embedding_model.name,
    crawl?.status,
    crawl?.result_location
  ];
}

/** Websites matching the search box: name, address, interval, model or crawl state. */
export function filterWebsites(websites: Website[], query: string): Website[] {
  return websites.filter((website) => matchesSearch(websiteSearchValues(website), query));
}

function collectionSearchValues(collection: Collection): SearchValue[] {
  return [
    collection.name,
    collection.embedding_model.name,
    collection.metadata.num_info_blobs,
    collection.metadata.num_info_blobs > 0 ? "files" : "empty"
  ];
}

/** Collections matching the search box: name, model or file count. */
export function filterCollections(collections: Collection[], query: string): Collection[] {
  return collections.filter((collection) =>
    matchesSearch(collectionSearchValues(collection), query)
  );
}

export const CRAWL_RUN_SORTS = [
  "started_desc",
  "started_asc",
  "status",
  "results_desc",
  "duration_desc"
] as const;

export type CrawlRunSort = (typeof CRAWL_RUN_SORTS)[number];

function normalized(value: string | null | undefined): string {
  return (value ?? "").trim().toLocaleLowerCase();
}

function compareText(a: string | null | undefined, b: string | null | undefined): number {
  return normalized(a).localeCompare(normalized(b));
}

function timestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function stableSort<T>(items: T[], compare: (a: T, b: T) => number): T[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const result = compare(a.item, b.item);
      return result === 0 ? a.index - b.index : result;
    })
    .map(({ item }) => item);
}

function crawlStartedAt(crawl: CrawlRun): number {
  return timestamp(crawl.created_at);
}

function crawlDurationMs(crawl: CrawlRun): number {
  const started = timestamp(crawl.created_at);
  const finished = timestamp(crawl.finished_at);
  if (started === 0 || finished === 0) return 0;
  return Math.max(0, finished - started);
}

function crawlResultCount(crawl: CrawlRun): number {
  return (crawl.pages_crawled ?? 0) + (crawl.files_downloaded ?? 0);
}

function crawlSearchValues(crawl: CrawlRun): SearchValue[] {
  return [
    crawl.status,
    crawl.result_location,
    crawl.created_at,
    crawl.finished_at,
    crawl.pages_crawled,
    crawl.files_downloaded,
    crawl.pages_failed,
    crawl.files_failed
  ];
}

export function filterAndSortCrawlRuns(
  runs: CrawlRun[],
  options: { query: string; sort: CrawlRunSort }
): CrawlRun[] {
  const filtered = runs.filter((run) => matchesSearch(crawlSearchValues(run), options.query));

  switch (options.sort) {
    case "started_asc":
      return stableSort(filtered, (a, b) => crawlStartedAt(a) - crawlStartedAt(b));
    case "status":
      return stableSort(filtered, (a, b) => compareText(a.status, b.status));
    case "results_desc":
      return stableSort(filtered, (a, b) => crawlResultCount(b) - crawlResultCount(a));
    case "duration_desc":
      return stableSort(filtered, (a, b) => crawlDurationMs(b) - crawlDurationMs(a));
    case "started_desc":
      return stableSort(filtered, (a, b) => crawlStartedAt(b) - crawlStartedAt(a));
  }
}
