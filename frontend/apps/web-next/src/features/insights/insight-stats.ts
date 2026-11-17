import { queryOptions } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { ChatPartner } from "@/lib/chat/types";
import {
  insightSourceQuery,
  type InsightFilters,
  type OpenableFindingKind
} from "./insight-figures";
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
 * `GET /analysis/conversation-insights/findings/`: what to look at in the
 * period, most affected first; empty when nothing passes the thresholds.
 */
export function insightFindingsQueryOptions(partner: Target, filters: InsightFilters) {
  const query = windowQuery(filters);
  return queryOptions({
    queryKey: ["conversation-insights", "findings", partner.type, partner.id, query],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/findings/", {
          params: { query: { ...query, ...insightPartnerQuery(partner) } },
          signal
        })
      )
  });
}

/** How many of the commonest questions "Vanligaste frågorna" lists. */
export const TOP_QUESTIONS_LIMIT = 10;

/** `GET /analysis/conversation-insights/questions/top/`: the commonest questions and how they fared. */
export function insightTopQuestionsQueryOptions(partner: Target, filters: InsightFilters) {
  const query = { ...windowQuery(filters), limit: TOP_QUESTIONS_LIMIT };
  return queryOptions({
    queryKey: ["conversation-insights", "top-questions", partner.type, partner.id, query],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/questions/top/", {
          params: { query: { ...query, ...insightPartnerQuery(partner) } },
          signal
        })
      )
  });
}

/** `GET /analysis/conversation-insights/knowledge/`: the knowledge the answers cited, and what none cited. */
export function insightKnowledgeQueryOptions(partner: Target, filters: InsightFilters) {
  const query = windowQuery(filters);
  return queryOptions({
    queryKey: ["conversation-insights", "knowledge", partner.type, partner.id, query],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/knowledge/", {
          params: { query: { ...query, ...insightPartnerQuery(partner) } },
          signal
        })
      )
  });
}

/** `GET /analysis/conversation-insights/tools/`: the tools the answers called, most called first. */
export function insightToolsQueryOptions(partner: Target, filters: InsightFilters) {
  const query = windowQuery(filters);
  return queryOptions({
    queryKey: ["conversation-insights", "tools", partner.type, partner.id, query],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/tools/", {
          params: { query: { ...query, ...insightPartnerQuery(partner) } },
          signal
        })
      )
  });
}

/** How many cases of a finding a page of its examples holds. */
export const FINDING_CASES_PAGE_SIZE = 20;

/**
 * `GET /analysis/conversation-insights/findings/{kind}/`: the cases behind a
 * finding, a page at a time from `cursor`.
 */
export function fetchFindingCases({
  partner,
  filters,
  kind,
  cursor,
  signal
}: {
  partner: Target;
  filters: InsightFilters;
  kind: OpenableFindingKind;
  cursor: string | undefined;
  signal?: AbortSignal;
}) {
  return unwrap(
    browserApi.GET("/api/v1/analysis/conversation-insights/findings/{kind}/", {
      params: {
        path: { kind },
        query: {
          ...windowQuery(filters),
          ...insightPartnerQuery(partner),
          limit: FINDING_CASES_PAGE_SIZE,
          cursor
        }
      },
      signal
    })
  );
}

/** The query key of a finding's cases: the target, the finding and the filters. */
export function findingCasesKey(
  partner: Target,
  filters: InsightFilters,
  kind: OpenableFindingKind
) {
  return [
    "conversation-insights",
    "finding-cases",
    partner.type,
    partner.id,
    kind,
    windowQuery(filters)
  ] as const;
}

/**
 * The target's insights are not the caller's to see: no insight access to it,
 * insights switched off for it, or (in a personal space) no insights
 * permission. The per-target endpoints answer 403 for each.
 */
export function isInsightRefusal(error: unknown): boolean {
  return error instanceof EneoApiError && error.status === 403;
}
