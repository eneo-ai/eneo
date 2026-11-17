import { calendarDate, type IsoDate } from "@/lib/calendar-date";
import {
  parseInsightSource,
  parseOpenableFinding,
  type InsightFilters,
  type OpenableFindingKind
} from "@/features/insights/insight-figures";
import {
  DEFAULT_INSIGHT_DAYS,
  insightRangeOfDays,
  type InsightRange
} from "@/features/insights/insights-range";

type SearchReader = Pick<URLSearchParams, "get">;

/** The period in `?from=&to=` (Svelte's calendar dates), or `fallback` for a missing or invalid one. */
export function readInsightRangeSearch(
  params: SearchReader,
  fallback = insightRangeOfDays(DEFAULT_INSIGHT_DAYS)
): InsightRange {
  const from = calendarDate(params.get("from"));
  const to = calendarDate(params.get("to"));
  return from && to && from <= to ? { start: from as IsoDate, end: to as IsoDate } : fallback;
}

/**
 * The insights view's filters in the address: the period (`from`, `to`),
 * the source (`source`, left out for every source) and the comparison
 * (`compare=1`). Anything unknown reads as the default.
 */
export function readInsightViewSearch(
  params: SearchReader,
  fallback = insightRangeOfDays(DEFAULT_INSIGHT_DAYS)
): InsightFilters {
  return {
    range: readInsightRangeSearch(params, fallback),
    source: parseInsightSource(params.get("source")),
    compare: params.get("compare") === "1"
  };
}

/** The address's query with the filters in it; other parameters stay. */
export function insightViewSearch(filters: InsightFilters, current = ""): string {
  const params = new URLSearchParams(current);
  params.set("from", filters.range.start);
  params.set("to", filters.range.end);
  if (filters.source) params.set("source", filters.source);
  else params.delete("source");
  if (filters.compare) params.set("compare", "1");
  else params.delete("compare");
  return `?${params.toString()}`;
}

/** The finding open in place of the overview (`finding`); anything unknown is none. */
export function readInsightFindingSearch(params: SearchReader): OpenableFindingKind | null {
  return parseOpenableFinding(params.get("finding"));
}

/** The address's query with the finding in it (none: left out); other parameters stay. */
export function insightFindingSearch(finding: OpenableFindingKind | null, current = ""): string {
  const params = new URLSearchParams(current);
  if (finding) params.set("finding", finding);
  else params.delete("finding");
  return `?${params.toString()}`;
}

/** Router search values are flat strings (or repeated strings), just like URLSearchParams. */
export function validateInsightViewSearch(
  search: Record<string, unknown>,
  fallback = insightRangeOfDays(DEFAULT_INSIGHT_DAYS)
): { from: string; to: string; source?: string; compare?: string; finding?: string } {
  const reader: SearchReader = {
    get: (key) => {
      const value = search[key];
      const first = Array.isArray(value) ? value[0] : value;
      return typeof first === "string" ? first : null;
    }
  };
  const filters = readInsightViewSearch(reader, fallback);
  const finding = readInsightFindingSearch(reader);
  return {
    from: filters.range.start,
    to: filters.range.end,
    ...(filters.source ? { source: filters.source } : {}),
    ...(filters.compare ? { compare: "1" } : {}),
    ...(finding ? { finding } : {})
  };
}
