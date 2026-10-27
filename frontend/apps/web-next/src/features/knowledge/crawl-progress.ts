import { isActiveCrawlRun } from "./crawl-run-state";
import type { CrawlRun, Website } from "./knowledge";

/** How often a running crawl is read again. */
export const ACTIVE_CRAWL_REFRESH_MS = 2_000;
/** How often a page with no running crawl looks for one (a schedule or another user can start one). */
export const IDLE_CRAWL_REFRESH_MS = 30_000;

/** The running crawl of each website that has one, by website id, as the space's crawl progress reads it. */
export type CrawlProgress = ReadonlyMap<string, CrawlRun>;

export function crawlProgressFrom(
  items: readonly { website_id: string; latest_crawl: CrawlRun }[]
): CrawlProgress {
  return new Map(items.map((item) => [item.website_id, item.latest_crawl]));
}

/** A run's timestamp in milliseconds; one it lacks sorts first. */
function time(value: string | null | undefined): number {
  return value ? Date.parse(value) : 0;
}

/** Whether `a` started after `b`, in the order the backend gives a website's runs. */
function startedLater(a: CrawlRun, b: CrawlRun): boolean {
  const byTime = time(a.created_at) - time(b.created_at);
  return byTime !== 0 ? byTime > 0 : a.id > b.id;
}

/**
 * The run to show for a website, of the one the space read and the one the
 * crawl progress read, which are refreshed apart: the crawl that started later;
 * of the same crawl, an ended read (an ended crawl never runs again), else the
 * later update.
 */
export function newerCrawlRun(fromSpace: CrawlRun | null, polled: CrawlRun | undefined) {
  if (!polled) return fromSpace;
  if (!fromSpace) return polled;
  if (fromSpace.id !== polled.id) return startedLater(polled, fromSpace) ? polled : fromSpace;
  if (!isActiveCrawlRun(fromSpace)) return fromSpace;
  return time(polled.updated_at) >= time(fromSpace.updated_at) ? polled : fromSpace;
}

/**
 * The websites with the newest known run of each: one list for the table, its
 * sorting and its actions. A website the progress does not change keeps its
 * identity, and so does the list when nothing changes.
 */
export function withCrawlProgress(
  websites: readonly Website[],
  progress: CrawlProgress | undefined
): Website[] {
  if (!progress || progress.size === 0) return websites as Website[];
  let changed = false;
  const merged = websites.map((website) => {
    const latest = newerCrawlRun(website.latest_crawl, progress.get(website.id));
    if (latest === website.latest_crawl) return website;
    changed = true;
    return { ...website, latest_crawl: latest };
  });
  return changed ? merged : (websites as Website[]);
}

/**
 * The crawls the websites show as running that the newer progress no longer
 * has (they ended, or another run took their place), as a key that names them.
 */
export function endedCrawls(websites: readonly Website[], progress: CrawlProgress): string {
  const ended = new Set<string>();
  for (const website of websites) {
    const shown = website.latest_crawl;
    if (shown && isActiveCrawlRun(shown) && progress.get(website.id)?.id !== shown.id) {
      ended.add(`${website.id}:${shown.id}`);
    }
  }
  return [...ended].join(" ");
}
