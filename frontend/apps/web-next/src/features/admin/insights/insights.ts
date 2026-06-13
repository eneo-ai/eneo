import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Counts = Schema<"Counts">;
export type MetadataStatisticsAggregated = Schema<"MetadataStatisticsAggregated">;
export type AssistantActivityStats = Schema<"AssistantActivityStats">;

export type InsightsRange = { start: string; end: string };

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
