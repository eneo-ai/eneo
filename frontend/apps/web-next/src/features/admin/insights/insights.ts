import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { insightSourceQuery, type InsightSource } from "@/features/insights/insight-figures";
import {
  browserTimeZone,
  insightRangeParams,
  type InsightRange
} from "@/features/insights/insights-range";

export type AssistantInsightQuestion = Schema<"AssistantInsightQuestion">;
export type AssistantInsightQuestionPage =
  Schema<"CursorPaginatedResponse_AssistantInsightQuestion_">;
export type InsightTarget = Schema<"InsightTarget">;
export type InsightTargetPage = Schema<"InsightTargetPage">;
export type InsightPersonalUsage = Schema<"InsightPersonalUsage">;

export type InsightsRange = { start: string; end: string };
export type AssistantInsightFilters = InsightsRange & {
  includeFollowups: boolean;
  /** One source's questions; every source's when left out. */
  source?: InsightSource | null;
};

/** The question history's page: as many as the feedback inbox and a finding's examples show. */
export const ASSISTANT_INSIGHT_QUESTION_LIMIT = 20;

/**
 * Logs are loaded only while their details dialog is mounted. Backend resource access stays authoritative.
 * `null`: the question has no log. It was not logged, or its log was emptied when content was removed;
 * the API answers 400 for both, and a retry cannot change that.
 */
export function questionLogQueryOptions(api: EneoClient, questionId: string) {
  return queryOptions({
    queryKey: ["admin-insights-question-log", questionId],
    gcTime: 0,
    queryFn: async ({ signal }): Promise<Schema<"MessageLogging"> | null> => {
      try {
        return await unwrap(
          api.GET("/api/v1/logging/{message_id}/", {
            params: { path: { message_id: questionId } },
            signal
          })
        );
      } catch (error) {
        if (error instanceof EneoApiError && error.status === 400) return null;
        throw error;
      }
    }
  });
}

export function fetchAssistantQuestionHistory({
  api,
  assistantId,
  filters,
  cursor,
  query,
  limit = ASSISTANT_INSIGHT_QUESTION_LIMIT
}: {
  api: EneoClient;
  assistantId: string;
  filters: AssistantInsightFilters;
  cursor?: string;
  query?: string;
  limit?: number;
}): Promise<AssistantInsightQuestionPage> {
  return unwrap(
    api.GET("/api/v1/analysis/assistants/{assistant_id}/questions/", {
      params: {
        path: { assistant_id: assistantId },
        query: {
          from_date: filters.start,
          to_date: filters.end,
          include_followups: filters.includeFollowups,
          ...insightSourceQuery(filters.source ?? null),
          cursor,
          limit,
          q: query
        }
      }
    })
  );
}

/** How the overview's table of assistants and group chats is sorted (server side). */
export type InsightTargetSort = {
  by: "name" | "conversations" | "questions";
  order: "asc" | "desc";
};

/** The table's sort before anyone picks another: the most used first. */
export const DEFAULT_INSIGHT_TARGET_SORT: InsightTargetSort = {
  by: "conversations",
  order: "desc"
};

export const INSIGHT_TARGETS_PAGE_SIZE = 25;
/** The endpoint's limit on the name search. */
export const INSIGHT_TARGETS_SEARCH_MAX = 200;

/**
 * `GET /analysis/targets/`: every assistant and group chat outside personal
 * spaces with its usage in the period (whole local days, the end exclusive),
 * a page of `limit` at a time from `offset`, and the personal spaces' usage,
 * the organisation's totals, the counts behind the filter and the active
 * users with it.
 */
export function fetchInsightTargets({
  api,
  range,
  compare,
  sort,
  search,
  unusedOnly,
  offset,
  limit = INSIGHT_TARGETS_PAGE_SIZE,
  signal
}: {
  api: EneoClient;
  range: InsightRange;
  compare: boolean;
  sort: InsightTargetSort;
  search: string;
  unusedOnly: boolean;
  offset: number;
  limit?: number;
  signal?: AbortSignal;
}): Promise<InsightTargetPage> {
  const { startTime, endTime } = insightRangeParams(range);
  return unwrap(
    api.GET("/api/v1/analysis/targets/", {
      params: {
        query: {
          start_time: startTime,
          end_time: endTime,
          compare,
          sort: sort.by,
          order: sort.order,
          q: search || undefined,
          activity: unusedOnly ? "unused" : "all",
          limit,
          offset
        }
      },
      signal
    })
  );
}

/**
 * The organisation's figures for the tiles: the target list unfiltered, one
 * row long, so a search, filter or sort of the table never moves them.
 */
export function insightTargetsSummaryQueryOptions(
  api: EneoClient,
  range: InsightRange,
  compare: boolean
) {
  return queryOptions({
    queryKey: ["admin-insights-targets", "summary", range, compare],
    queryFn: ({ signal }) =>
      fetchInsightTargets({
        api,
        range,
        compare,
        sort: DEFAULT_INSIGHT_TARGET_SORT,
        search: "",
        unusedOnly: false,
        offset: 0,
        limit: 1,
        signal
      })
  });
}

/**
 * `GET /analysis/targets/activity/`: the organisation's conversations and
 * questions per local day by source, in the browser's time zone.
 */
export function insightTargetsActivityQueryOptions(api: EneoClient, range: InsightRange) {
  const { startTime, endTime } = insightRangeParams(range);
  const query = { start_time: startTime, end_time: endTime, timezone: browserTimeZone() };
  return queryOptions({
    queryKey: ["admin-insights-activity", query],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/v1/analysis/targets/activity/", { params: { query }, signal }))
  });
}

/** The offset of the page after `page`, or undefined after the last. */
export function nextTargetOffset(page: {
  offset: number;
  items: readonly unknown[];
  total_count: number;
}): number | undefined {
  const next = page.offset + page.items.length;
  return page.items.length > 0 && next < page.total_count ? next : undefined;
}

/** Inclusive datetime endpoints need the last microsecond before the next local midnight. */
export function insightPeriod(range: InsightRange): InsightsRange {
  const { startTime, endTime } = insightRangeParams(range);
  return {
    start: startTime,
    end: new Date(new Date(endTime).getTime() - 1).toISOString().replace(".999Z", ".999999Z")
  };
}
