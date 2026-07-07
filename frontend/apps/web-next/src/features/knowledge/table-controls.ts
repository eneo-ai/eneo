import { formatWebsiteName, type Collection, type CrawlRun, type Website } from "./knowledge";

export const WEBSITE_SORTS = [
  "name_asc",
  "name_desc",
  "latest_crawl_desc",
  "latest_crawl_asc",
  "status",
  "auto_updates"
] as const;

export const COLLECTION_SORTS = ["name_asc", "name_desc", "files_desc", "files_asc"] as const;

export const CRAWL_RUN_SORTS = [
  "started_desc",
  "started_asc",
  "status",
  "results_desc",
  "duration_desc"
] as const;

export type WebsiteSort = (typeof WEBSITE_SORTS)[number];
export type CollectionSort = (typeof COLLECTION_SORTS)[number];
export type CrawlRunSort = (typeof CRAWL_RUN_SORTS)[number];

function normalized(value: string | null | undefined): string {
  return (value ?? "").trim().toLocaleLowerCase();
}

function searchTerms(query: string): string[] {
  return normalized(query).split(/\s+/).filter(Boolean);
}

function matchesQuery(values: (string | number | null | undefined)[], query: string): boolean {
  const terms = searchTerms(query);
  if (terms.length === 0) return true;
  const haystack = values
    .map((value) => normalized(value == null ? undefined : String(value)))
    .filter(Boolean)
    .join(" ");
  return terms.every((term) => haystack.includes(term));
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

function websiteLastCrawlAt(website: Website): number {
  return timestamp(website.latest_crawl?.finished_at ?? website.latest_crawl?.created_at);
}

function websiteSearchValues(website: Website): (string | number | null | undefined)[] {
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

export function filterAndSortWebsites(
  websites: Website[],
  options: { query: string; sort: WebsiteSort }
): Website[] {
  const filtered = websites.filter((website) =>
    matchesQuery(websiteSearchValues(website), options.query)
  );

  switch (options.sort) {
    case "name_desc":
      return stableSort(filtered, (a, b) =>
        compareText(formatWebsiteName(b), formatWebsiteName(a))
      );
    case "latest_crawl_desc":
      return stableSort(filtered, (a, b) => websiteLastCrawlAt(b) - websiteLastCrawlAt(a));
    case "latest_crawl_asc":
      return stableSort(filtered, (a, b) => websiteLastCrawlAt(a) - websiteLastCrawlAt(b));
    case "status":
      return stableSort(filtered, (a, b) =>
        compareText(a.latest_crawl?.status, b.latest_crawl?.status)
      );
    case "auto_updates":
      return stableSort(filtered, (a, b) => compareText(a.update_interval, b.update_interval));
    case "name_asc":
      return stableSort(filtered, (a, b) =>
        compareText(formatWebsiteName(a), formatWebsiteName(b))
      );
  }
}

function collectionSearchValues(collection: Collection): (string | number | null | undefined)[] {
  return [
    collection.name,
    collection.embedding_model.name,
    collection.metadata.num_info_blobs,
    collection.metadata.num_info_blobs > 0 ? "files" : "empty"
  ];
}

export function filterAndSortCollections(
  collections: Collection[],
  options: { query: string; sort: CollectionSort }
): Collection[] {
  const filtered = collections.filter((collection) =>
    matchesQuery(collectionSearchValues(collection), options.query)
  );

  switch (options.sort) {
    case "name_desc":
      return stableSort(filtered, (a, b) => compareText(b.name, a.name));
    case "files_desc":
      return stableSort(filtered, (a, b) => b.metadata.num_info_blobs - a.metadata.num_info_blobs);
    case "files_asc":
      return stableSort(filtered, (a, b) => a.metadata.num_info_blobs - b.metadata.num_info_blobs);
    case "name_asc":
      return stableSort(filtered, (a, b) => compareText(a.name, b.name));
  }
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

function crawlSearchValues(crawl: CrawlRun): (string | number | null | undefined)[] {
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
  const filtered = runs.filter((run) => matchesQuery(crawlSearchValues(run), options.query));

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
