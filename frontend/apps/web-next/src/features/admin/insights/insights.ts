import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

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

export function insightCountsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-insights-counts"],
    queryFn: (): Promise<Counts> => unwrap(api.GET("/api/v1/analysis/counts/"))
  });
}

/** Per-day time series of assistants / sessions / questions over a date range. */
export function insightAggregatedQueryOptions(api: EneoClient, range: InsightsRange) {
  return queryOptions({
    queryKey: ["admin-insights-aggregated", range],
    queryFn: (): Promise<MetadataStatisticsAggregated> =>
      unwrap(
        api.GET("/api/v1/analysis/metadata-statistics/aggregated/", {
          params: { query: { start_date: range.start, end_date: range.end } }
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
  question
}: {
  api: EneoClient;
  assistantId: string;
  filters: AssistantInsightFilters;
  question: string;
}): Promise<string> {
  const response = await unwrap(
    api.POST("/api/v1/analysis/assistants/{assistant_id}/", {
      params: {
        path: { assistant_id: assistantId },
        query: {
          from_date: filters.start,
          to_date: filters.end,
          include_followups: filters.includeFollowups
        }
      },
      body: { question, stream: false }
    })
  );
  return analysisAnswerText(response) ?? "";
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

/**
 * Merge the three per-day series into chart rows keyed by day. Buckets present
 * in any series are filled (missing → 0) so the chart has no gaps.
 */
export function mergeInsightSeries(
  data: MetadataStatisticsAggregated
): { date: string; assistants: number; sessions: number; questions: number }[] {
  const byDay = new Map<string, { assistants: number; sessions: number; questions: number }>();
  const ensure = (iso: string) => {
    const day = iso.slice(0, 10);
    let row = byDay.get(day);
    if (!row) {
      row = { assistants: 0, sessions: 0, questions: 0 };
      byDay.set(day, row);
    }
    return row;
  };
  for (const point of data.assistants) ensure(point.created_at).assistants += point.count;
  for (const point of data.sessions) ensure(point.created_at).sessions += point.count;
  for (const point of data.questions) ensure(point.created_at).questions += point.count;
  return [...byDay.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([date, counts]) => ({ date, ...counts }));
}
