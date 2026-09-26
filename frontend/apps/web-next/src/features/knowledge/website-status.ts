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

/**
 * Sort rank of a status, problems first: failed, warnings, running, queued,
 * never crawled or skipped, done. Derived from the status itself, so a table
 * sorts by exactly what its status column says.
 */
export function statusRank(status: KnowledgeStatus): number {
  switch (status.tone) {
    case "error":
      return 0;
    case "warning":
      return 1;
    case "accent":
      return status.isPulsing ? 2 : 3;
    case "neutral":
      return 4;
    case "success":
      return 5;
  }
}

/**
 * When the website was last synced: the latest crawl's finish time if that
 * crawl completed. A running, queued, failed or skipped crawl says nothing
 * about the last successful sync (the API only returns the latest crawl).
 */
export function websiteSyncedAt(website: Website): string | null {
  const crawl = website.latest_crawl;
  return crawl?.status === "complete" ? (crawl.finished_at ?? null) : null;
}

/** A sync older than this is flagged as stale, as in the Svelte app. */
export const STALE_SYNC_DAYS = 10;

const DAY_MS = 24 * 60 * 60 * 1000;

const INTERVAL_DAYS: Partial<Record<Website["update_interval"], number>> = {
  daily: 1,
  every_other_day: 2,
  weekly: 7
};

/**
 * When automatic updates crawl the website next: its latest crawl plus the
 * interval. `null` before the first crawl (scheduled after it), `undefined`
 * when automatic updates are off.
 */
export function nextCrawlAt(website: Website): string | null | undefined {
  const days = INTERVAL_DAYS[website.update_interval];
  if (days === undefined) return undefined;
  const last = website.latest_crawl?.finished_at ?? website.latest_crawl?.created_at;
  if (!last) return null;
  return new Date(Date.parse(last) + days * DAY_MS).toISOString();
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * "3 sidor", "1 fil" or "3 sidor och 1 fil", with plural forms: the kinds
 * that occurred, pages when neither did.
 */
export function pagesAndFilesText(t: Translate, pages: number, files: number): string {
  const pageText = t("space_pages_count", { count: pages });
  const fileText = t("space_files_count", { count: files });
  if (pages > 0 && files > 0)
    return t("space_pages_and_files", { pages: pageText, files: fileText });
  return files > 0 ? fileText : pageText;
}

/** "2 sidor misslyckades" for a crawl that completed with warnings; undefined without failures. */
export function crawlFailuresText(t: Translate, crawl: CrawlRun): string | undefined {
  const pages = crawl.pages_failed ?? 0;
  const files = crawl.files_failed ?? 0;
  if (pages === 0 && files === 0) return undefined;
  return t("space_crawl_failed", { items: pagesAndFilesText(t, pages, files) });
}
