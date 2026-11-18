import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { insightSourceQuery, type InsightSource } from "@/features/insights/insight-figures";
import { insightRangeParams, type InsightRange } from "@/features/insights/insights-range";
import { isoDate, type IsoDate } from "@/lib/calendar-date";

export type Counts = Schema<"Counts">;
export type MetadataStatisticsAggregated = Schema<"MetadataStatisticsAggregated">;
export type AssistantActivityStats = Schema<"AssistantActivityStats">;
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

/** Hourly counts of assistants / sessions / questions over a date range. */
export function insightAggregatedQueryOptions(
  api: EneoClient,
  range: InsightsRange,
  timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
) {
  return queryOptions({
    queryKey: ["admin-insights-aggregated", range, timeZone],
    queryFn: ({ signal }): Promise<MetadataStatisticsAggregated> =>
      unwrap(
        api.GET("/api/v1/analysis/metadata-statistics/aggregated/", {
          params: { query: { start_date: range.start, end_date: range.end, time_zone: timeZone } },
          signal
        })
      )
  });
}

/** Active-assistant / active-user activity summary over a date range. */
export function insightActivityQueryOptions(api: EneoClient, range: InsightsRange) {
  return queryOptions({
    queryKey: ["admin-insights-activity", range],
    queryFn: (): Promise<AssistantActivityStats> =>
      unwrap(
        api.GET("/api/v1/analysis/assistant-activity/", {
          params: { query: { start_date: range.start, end_date: range.end } }
        })
      )
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

export const INSIGHT_TARGETS_PAGE_SIZE = 25;
/** The endpoint's limit on the name search. */
export const INSIGHT_TARGETS_SEARCH_MAX = 200;

/**
 * `GET /analysis/targets/`: every assistant and group chat outside personal
 * spaces with its usage in the period (whole local days, the end exclusive),
 * a page at a time from `offset`, and the personal spaces' usage together.
 */
export function fetchInsightTargets({
  api,
  range,
  compare,
  sort,
  search,
  unusedOnly,
  offset,
  signal
}: {
  api: EneoClient;
  range: InsightRange;
  compare: boolean;
  sort: InsightTargetSort;
  search: string;
  unusedOnly: boolean;
  offset: number;
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
          limit: INSIGHT_TARGETS_PAGE_SIZE,
          offset
        }
      },
      signal
    })
  );
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

export function shiftInsightDate(value: string, days: number): IsoDate {
  const date = new Date(`${value}T12:00:00`);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

export function insightDayCount(range: InsightRange): number {
  return Math.round((Date.parse(range.end) - Date.parse(range.start)) / 86_400_000) + 1;
}

/** Equal number of calendar days, including across a change of UTC offset. */
export function previousInsightRange(range: InsightRange): InsightRange {
  const days = insightDayCount(range);
  return { start: shiftInsightDate(range.start, -days), end: shiftInsightDate(range.start, -1) };
}

export function periodTotals(data: MetadataStatisticsAggregated): Counts {
  const sum = (points: MetadataStatisticsAggregated["sessions"]) =>
    points.reduce((total, point) => total + point.count, 0);
  return {
    assistants: sum(data.assistants),
    sessions: sum(data.sessions),
    questions: sum(data.questions)
  };
}

/** A zero baseline with new activity has no finite percentage. */
export function insightTrend(current: number, previous: number): number | null {
  return previous === 0
    ? current === 0
      ? 0
      : null
    : Math.round(((current - previous) / previous) * 100);
}

export type InsightGrouping = "date" | "weekday" | "hour";
export type InsightChartRow = Counts & { date: string };

/** Backend buckets are instants; all grouping follows the viewer's local day, like the range picker. */
export function groupedInsightSeries(
  data: MetadataStatisticsAggregated,
  grouping: InsightGrouping
): InsightChartRow[] {
  const rows = new Map<string, InsightChartRow>();
  const ensure = (date: string) => {
    let row = rows.get(date);
    if (!row) {
      row = { date, assistants: 0, sessions: 0, questions: 0 };
      rows.set(date, row);
    }
    return row;
  };
  if (grouping !== "date") {
    for (let index = 0; index < (grouping === "hour" ? 24 : 7); index++) ensure(String(index));
  }
  for (const metric of ["assistants", "sessions", "questions"] as const) {
    for (const point of data[metric]) {
      const instant = new Date(point.created_at);
      const key =
        grouping === "date"
          ? isoDate(instant)
          : String(grouping === "hour" ? instant.getHours() : (instant.getDay() + 6) % 7);
      ensure(key)[metric] += point.count;
    }
  }
  return [...rows.values()].sort((a, b) =>
    grouping === "date" ? a.date.localeCompare(b.date) : Number(a.date) - Number(b.date)
  );
}
