import { matchesSearch, type SearchValue } from "@/features/spaces/resource-filter";
import { formatWebsiteName, type Collection, type CrawlRun, type Website } from "./knowledge";

/**
 * Search predicates for the knowledge tables' filter boxes. The tables sort by
 * their column headers (Astryx Table's sortable plugin, knowledge-sort.ts).
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

/** Crawl runs matching the search box: status, failure reason, times or counts. */
export function filterCrawlRuns(runs: CrawlRun[], query: string): CrawlRun[] {
  return runs.filter((run) => matchesSearch(crawlSearchValues(run), query));
}
