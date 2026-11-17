import { queryOptions } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import { insightSourceQuery, type InsightFilters } from "./insight-figures";
import { browserTimeZone, insightPartnerQuery, insightRangeParams } from "./insights-range";

type Target = Pick<ChatPartner, "type" | "id">;

/**
 * The period of the filters as the per-day endpoints take it: whole local
 * days from the first day's midnight up to the midnight after the last
 * (exclusive), and the browser's time zone those days are counted in.
 */
function windowQuery(filters: InsightFilters) {
  const { startTime, endTime } = insightRangeParams(filters.range);
  return {
    start_time: startTime,
    end_time: endTime,
    timezone: browserTimeZone(),
    ...insightSourceQuery(filters.source)
  };
}

/**
 * `GET /analysis/conversation-insights/summary/`: the period's figures for an
 * assistant or group chat, and with `compare` the previous period's beside
 * them.
 */
export function insightSummaryQueryOptions(partner: Target, filters: InsightFilters) {
  const query = { ...windowQuery(filters), compare: filters.compare };
  return queryOptions({
    queryKey: ["conversation-insights", "summary", partner.type, partner.id, query],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/summary/", {
          params: { query: { ...query, ...insightPartnerQuery(partner) } },
          signal
        })
      )
  });
}

/** `GET /analysis/conversation-insights/activity/`: conversations per local day by source. */
export function insightActivityQueryOptions(partner: Target, filters: InsightFilters) {
  const query = windowQuery(filters);
  return queryOptions({
    queryKey: ["conversation-insights", "activity", partner.type, partner.id, query],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/activity/", {
          params: { query: { ...query, ...insightPartnerQuery(partner) } },
          signal
        })
      )
  });
}

/**
 * The target's insights are not the caller's to see: no insight access to it,
 * insights switched off for it, or (in a personal space) no insights
 * permission. The per-target endpoints answer 403 for each.
 */
export function isInsightRefusal(error: unknown): boolean {
  return error instanceof EneoApiError && error.status === 403;
}
