import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { cursorPagination } from "@/lib/api/pagination";
import { CRAWL_FAILURES_PAGE_SIZE, type CrawlFailure } from "@/features/knowledge/knowledge";

/**
 * The admin crawler endpoints (/admin/crawler): tenant-wide crawl metadata
 * for administrators, without access to the indexed content.
 */

export type CrawlerItem = Schema<"AdminCrawlerItem">;
export type CrawlerDetails = Schema<"AdminCrawlerDetails">;
export type CrawlerSchedulerHealth = Schema<"AdminCrawlerSchedulerHealth">;
export type CrawlerScheduledWebsite = Schema<"AdminCrawlerScheduledWebsite">;
export type CrawlerRelatedWebsite = Schema<"AdminCrawlerRelatedWebsite">;

type OverviewQuery = {
  view?: "active" | "recent" | "all";
  status?: CrawlerStatusFilter;
  period?: CrawlerPeriod;
  time_zone?: string;
  search?: string;
  limit?: number;
  cursor?: string | null;
};

export type CrawlerPeriod = Schema<"CrawlHistoryPeriod">;
export type CrawlerView = "active" | "recent" | "all" | "schedule";

/** The status filter the overview accepts: a phase, an outcome or one of its groups. */
export type CrawlerStatusFilter =
  | "queued"
  | "running"
  | "finalizing"
  | "stopping"
  | "completed"
  | "warnings"
  | "unsuccessful"
  | "cancelled"
  | "issues";

export type ScheduleInterval = CrawlerScheduledWebsite["update_interval"];
export type ScheduleStateFilter = "due" | "waiting" | "blocked";
export type ScheduleSort = "next_due" | "last_crawled" | "url";

type ScheduleQuery = {
  search?: string;
  interval?: ScheduleInterval;
  state?: ScheduleStateFilter;
  sort?: ScheduleSort;
  limit?: number;
  cursor?: string | null;
};

/** Rows per page of the overview and schedule tables. */
export const CRAWLER_PAGE_SIZE = 50;
/** Rows per page of a website's history and address matches in the details. */
export const CRAWLER_DETAIL_PAGE_SIZE = 10;

export function crawlerOverviewQueryOptions(api: EneoClient, query: OverviewQuery) {
  return queryOptions({
    queryKey: ["admin", "crawler", "overview", query],
    queryFn: () => unwrap(api.GET("/api/v1/admin/crawler/", { params: { query } }))
  });
}

export function crawlerScheduleQueryOptions(api: EneoClient, query: ScheduleQuery) {
  return queryOptions({
    queryKey: ["admin", "crawler", "schedule", query],
    queryFn: () => unwrap(api.GET("/api/v1/admin/crawler/websites/", { params: { query } }))
  });
}

export function crawlerDetailsQueryOptions(api: EneoClient, runId: string) {
  return queryOptions({
    queryKey: ["admin", "crawler", "runs", runId],
    queryFn: () =>
      unwrap(api.GET("/api/v1/admin/crawler/runs/{id}/", { params: { path: { id: runId } } }))
  });
}

/** The failures of a run, from the admin endpoint (same shape as the website's). */
export function crawlerFailuresQueryOptions(
  api: EneoClient,
  runId: string,
  kind: CrawlFailure["kind"] | null
) {
  return infiniteQueryOptions({
    ...cursorPagination,
    queryKey: ["admin", "crawler", "runs", runId, "failures", kind],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/admin/crawler/runs/{id}/failures/", {
          params: {
            path: { id: runId },
            query: { limit: CRAWL_FAILURES_PAGE_SIZE, cursor: pageParam, kind }
          }
        })
      )
  });
}

export function crawlerWebsiteRunsQueryOptions(
  api: EneoClient,
  websiteId: string,
  cursor: string | null
) {
  return queryOptions({
    queryKey: ["admin", "crawler", "websites", websiteId, "runs", cursor],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/admin/crawler/websites/{id}/runs/", {
          params: { path: { id: websiteId }, query: { limit: CRAWLER_DETAIL_PAGE_SIZE, cursor } }
        })
      )
  });
}

export function crawlerWebsiteMatchesQueryOptions(
  api: EneoClient,
  websiteId: string,
  cursor: string | null
) {
  return queryOptions({
    queryKey: ["admin", "crawler", "websites", websiteId, "matches", cursor],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/admin/crawler/websites/{id}/matches/", {
          params: { path: { id: websiteId }, query: { limit: CRAWLER_DETAIL_PAGE_SIZE, cursor } }
        })
      )
  });
}
