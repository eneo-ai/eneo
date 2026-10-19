import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { crawlerOverviewQueryOptions } from "@/features/admin/crawler/crawler";
import { tokenUsageQueryOptions } from "@/features/admin/usage/usage";
import { adminUsersQueryOptions } from "@/features/admin/users/users";

/**
 * The admin landing's queries. Three reuse the query of the page their card
 * links to, so the cache entry is shared and that page opens with its data
 * already there.
 */

/** How many audit events the landing lists. */
export const OVERVIEW_AUDIT_EVENTS = 5;

/** Active users: the first page the Användare page shows, whose metadata carries the counts. */
export function overviewUsersQueryOptions(api: EneoClient) {
  return adminUsersQueryOptions(api, { page: 1, stateFilter: "active", search: "" });
}

/** Token usage over the backend's default range, the last 30 days (the Användning page's query). */
export function overviewUsageQueryOptions(api: EneoClient) {
  return tokenUsageQueryOptions(api);
}

/** The crawler's tenant-wide totals and scheduler health; one row, the landing needs the summary only. */
export function overviewCrawlerQueryOptions(api: EneoClient) {
  return crawlerOverviewQueryOptions(api, { view: "active", limit: 1 });
}

/**
 * The latest audit events. The Granskningsloggar page fetches 100 rows a
 * page, so this asks for its own short page. The key shares the page's
 * "audit-logs" prefix: when a justification opens an access session, that
 * page's invalidation refetches this list too.
 */
export function latestAuditEventsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["audit-logs", "latest", OVERVIEW_AUDIT_EVENTS],
    retry: false, // a 401 means "needs an access session", not a transient error
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/audit/logs", {
          params: { query: { page: 1, page_size: OVERVIEW_AUDIT_EVENTS } }
        })
      )
  });
}
