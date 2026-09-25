import type { StatusTone } from "@/components/composites/status-label";
import type { CrawlRun, Website } from "./knowledge";

/** A status for a status-dot cell: tone, translation key and optional fix link. */
export type KnowledgeStatus = {
  tone: StatusTone;
  labelKey: string;
  isPulsing?: boolean;
  /** Where the problem can be fixed ("Åtgärda"). */
  fixHref?: string;
};

const SKIPPED_PREFIX = "skipped duplicate crawl";

/** A failed crawl that only stood aside for an identical crawl already running. */
export function isSkippedCrawl(crawl: CrawlRun | null | undefined): boolean {
  return (
    crawl?.status === "failed" &&
    crawl.result_location?.toLowerCase().startsWith(SKIPPED_PREFIX) === true
  );
}

/** Finished, but some pages or files could not be read. */
export function crawlHasWarnings(crawl: CrawlRun): boolean {
  return (
    crawl.status === "complete" && ((crawl.pages_failed ?? 0) > 0 || (crawl.files_failed ?? 0) > 0)
  );
}

/** State of one crawl run, for the website's crawl history. */
export function crawlRunStatus(crawl: CrawlRun): KnowledgeStatus {
  if (isSkippedCrawl(crawl)) return { tone: "neutral", labelKey: "crawl_skipped" };
  switch (crawl.status) {
    case "queued":
      return { tone: "accent", labelKey: "queued" };
    case "in progress":
      return { tone: "accent", labelKey: "in_progress", isPulsing: true };
    case "complete":
      return crawlHasWarnings(crawl)
        ? { tone: "warning", labelKey: "crawl_completed_with_warnings" }
        : { tone: "success", labelKey: "complete" };
    default:
      return { tone: "error", labelKey: "failed" };
  }
}

/**
 * Latest-crawl state of a website, shared by the space overview and the
 * websites tab so both say the same thing. The crawl API has no progress
 * figure, so an in-progress crawl has no percentage. With `detailHref`, a
 * failed crawl links to the website page, where it can be run again.
 */
export function websiteStatus(website: Website, detailHref?: string): KnowledgeStatus {
  const crawl = website.latest_crawl;
  if (!crawl) return { tone: "neutral", labelKey: "website_not_yet_crawled" };
  if (isSkippedCrawl(crawl)) return { tone: "neutral", labelKey: "sync_skipped" };
  switch (crawl.status) {
    case "queued":
      return { tone: "accent", labelKey: "queued" };
    case "in progress":
      return { tone: "accent", labelKey: "space_status_syncing", isPulsing: true };
    case "complete":
      return crawlHasWarnings(crawl)
        ? { tone: "warning", labelKey: "synced_with_warnings" }
        : { tone: "success", labelKey: "space_status_indexed" };
    default:
      return {
        tone: "error",
        labelKey: "space_status_sync_error",
        ...(detailHref ? { fixHref: detailHref } : {})
      };
  }
}
