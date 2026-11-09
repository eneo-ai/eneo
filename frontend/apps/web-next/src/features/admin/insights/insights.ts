import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { insightRangeParams, type InsightRange } from "@/features/insights/insights-range";
import { isoDate, type IsoDate } from "@/lib/calendar-date";
import { readEventStream } from "@/lib/api/event-stream";

export type Counts = Schema<"Counts">;
export type MetadataStatistics = Schema<"MetadataStatistics">;
export type MetadataStatisticsAggregated = Schema<"MetadataStatisticsAggregated">;
export type AssistantActivityStats = Schema<"AssistantActivityStats">;
export type AssistantInsightQuestion = Schema<"AssistantInsightQuestion">;
export type AssistantInsightQuestionPage =
  Schema<"CursorPaginatedResponse_AssistantInsightQuestion_">;
export type TenantAssistant = Schema<"AssistantPublic">;

export type InsightsRange = { start: string; end: string };
export type AssistantInsightFilters = InsightsRange & { includeFollowups: boolean };

export const ASSISTANT_INSIGHT_QUESTION_LIMIT = 100;

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

/** Raw insight metadata for assistant-level drill-down links over a date range. */
export function insightMetadataQueryOptions(api: EneoClient, range: InsightsRange) {
  return queryOptions({
    queryKey: ["admin-insights-metadata", range],
    queryFn: (): Promise<MetadataStatistics> =>
      unwrap(
        api.GET("/api/v1/analysis/metadata-statistics/", {
          params: { query: { start_date: range.start, end_date: range.end } }
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

/** Admin-visible assistants for resolving metadata assistant ids to names. */
export function tenantAssistantsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-insights-tenant-assistants"],
    queryFn: async (): Promise<TenantAssistant[]> => {
      const page = await unwrap(
        api.GET("/api/v1/assistants/", { params: { query: { for_tenant: true } } })
      );
      return page.items;
    }
  });
}

export function assistantQuestionHistoryQueryOptions({
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
}) {
  return queryOptions({
    queryKey: ["admin-insights-assistant-questions", assistantId, filters, query, cursor, limit],
    queryFn: (): Promise<AssistantInsightQuestionPage> =>
      fetchAssistantQuestionHistory({ api, assistantId, filters, cursor, query, limit })
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
          cursor,
          limit,
          q: query
        }
      }
    })
  );
}

export async function askAssistantInsightQuestion({
  api,
  assistantId,
  filters,
  question,
  signal,
  onAnswer
}: {
  api: EneoClient;
  assistantId: string;
  filters: AssistantInsightFilters;
  question: string;
  signal?: AbortSignal;
  onAnswer?: (part: string) => void;
}): Promise<string> {
  const body = await unwrap(
    api.POST("/api/v1/analysis/assistants/{assistant_id}/", {
      params: {
        path: { assistant_id: assistantId },
        query: {
          from_date: filters.start,
          to_date: filters.end,
          include_followups: filters.includeFollowups
        }
      },
      body: { question, stream: true } satisfies Schema<"AskAnalysis">,
      parseAs: "stream",
      signal
    })
  );
  if (!body) throw new Error("The analysis response had no stream.");
  let answer = "";
  await readEventStream(body, (data) => {
    signal?.throwIfAborted();
    if (!data) return;
    const part = analysisAnswerText(JSON.parse(data));
    if (part === null) throw new Error("The analysis stream contained an invalid answer.");
    answer += part;
    onAnswer?.(part);
  });
  signal?.throwIfAborted();
  if (!answer.trim()) throw new Error("The analysis stream returned no answer.");
  return answer;
}

export function analysisAnswerText(response: unknown): string | null {
  if (typeof response !== "object" || response === null || Array.isArray(response)) return null;
  const answer = (response as Record<string, unknown>).answer;
  return typeof answer === "string" ? answer : null;
}

export type AssistantActivityRow = {
  assistantId: string;
  sessions: number;
  questions: number;
  latestAt: string;
};

/** Aggregates raw metadata into assistant rows sorted by visible activity. */
export function assistantActivityRows(data: MetadataStatistics, limit = 6): AssistantActivityRow[] {
  const rows = new Map<string, AssistantActivityRow>();
  const ensure = (assistantId: string, createdAt: string) => {
    let row = rows.get(assistantId);
    if (!row) {
      row = { assistantId, sessions: 0, questions: 0, latestAt: createdAt };
      rows.set(assistantId, row);
    }
    if (createdAt > row.latestAt) row.latestAt = createdAt;
    return row;
  };

  for (const session of data.sessions) {
    if (!session.assistant_id) continue;
    ensure(session.assistant_id, session.created_at).sessions += 1;
  }

  for (const question of data.questions) {
    if (!question.assistant_id) continue;
    ensure(question.assistant_id, question.created_at).questions += 1;
  }

  return [...rows.values()]
    .sort(
      (a, b) =>
        b.questions - a.questions ||
        b.sessions - a.sessions ||
        (a.latestAt < b.latestAt ? 1 : -1) ||
        a.assistantId.localeCompare(b.assistantId)
    )
    .slice(0, limit);
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
