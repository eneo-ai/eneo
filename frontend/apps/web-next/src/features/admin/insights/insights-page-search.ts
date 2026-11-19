import { calendarDate } from "@/lib/calendar-date";
import {
  DEFAULT_INSIGHT_DAYS,
  insightRangeOfDays,
  type InsightRange
} from "@/features/insights/insights-range";
import { readInsightRangeSearch } from "./assistant-insights-view";
import {
  DEFAULT_INSIGHT_TARGET_SORT,
  INSIGHT_TARGETS_SEARCH_MAX,
  type InsightTargetSort
} from "./insights";

type SearchReader = Pick<URLSearchParams, "get">;

/**
 * What the organisation's insights page keeps in its address, so a way back
 * from an assistant's insights finds it as it was: the period (`from`, `to`),
 * the comparison (`compare=1`), "Oanvända" (`activity=unused`), the name
 * search (`q`) and the table's sort (`sort`, `order`). Defaults are left out.
 */
export type InsightsPageState = {
  range: InsightRange;
  compare: boolean;
  unusedOnly: boolean;
  /** The name search as sent: trimmed and within the endpoint's limit. */
  search: string;
  sort: InsightTargetSort;
};

const SORT_KEYS = ["name", "conversations", "questions"] as const;

/** The trimmed name search the endpoint takes. */
export function insightTargetSearch(value: string): string {
  return value.trim().slice(0, INSIGHT_TARGETS_SEARCH_MAX);
}

/** The page's state from its address; anything missing or unknown reads as the default. */
export function readInsightsPageSearch(
  params: SearchReader,
  fallback = insightRangeOfDays(DEFAULT_INSIGHT_DAYS)
): InsightsPageState {
  const by = SORT_KEYS.find((key) => key === params.get("sort"));
  const order = params.get("order");
  return {
    range: readInsightRangeSearch(params, fallback),
    compare: params.get("compare") === "1",
    unusedOnly: params.get("activity") === "unused",
    search: insightTargetSearch(params.get("q") ?? ""),
    sort: by
      ? {
          by,
          // A column's first order: names A to Z, figures largest first.
          order: order === "asc" || order === "desc" ? order : by === "name" ? "asc" : "desc"
        }
      : DEFAULT_INSIGHT_TARGET_SORT
  };
}

/** The address's query for the page's state, defaults left out. */
export function insightsPageSearch(
  state: InsightsPageState,
  fallback = insightRangeOfDays(DEFAULT_INSIGHT_DAYS)
): string {
  const params = new URLSearchParams();
  if (state.range.start !== fallback.start || state.range.end !== fallback.end) {
    params.set("from", state.range.start);
    params.set("to", state.range.end);
  }
  if (state.compare) params.set("compare", "1");
  if (state.unusedOnly) params.set("activity", "unused");
  if (state.search) params.set("q", state.search);
  const sort = state.sort;
  if (
    sort.by !== DEFAULT_INSIGHT_TARGET_SORT.by ||
    sort.order !== DEFAULT_INSIGHT_TARGET_SORT.order
  ) {
    params.set("sort", sort.by);
    params.set("order", sort.order);
  }
  return `?${params.toString()}`;
}

/** The organisation's insights on a period, as the way back from an assistant's insights. */
export function insightsPageHref(range: InsightRange, compare: boolean): string {
  const search = insightsPageSearch({
    range,
    compare,
    unusedOnly: false,
    search: "",
    sort: DEFAULT_INSIGHT_TARGET_SORT
  });
  return search === "?" ? "/admin/insights" : `/admin/insights${search}`;
}

/**
 * Router search values are flat strings (or repeated strings), as
 * URLSearchParams has them. What is valid stays as it was given; anything
 * else is left out.
 */
export function validateInsightsPageSearch(search: Record<string, unknown>): {
  from?: string;
  to?: string;
  compare?: string;
  activity?: string;
  q?: string;
  sort?: string;
  order?: string;
} {
  const get = (key: string) => {
    const value = search[key];
    const first = Array.isArray(value) ? value[0] : value;
    return typeof first === "string" ? first : null;
  };
  // A period is kept only whole and in order.
  const from = calendarDate(get("from"));
  const to = calendarDate(get("to"));
  const state = readInsightsPageSearch({ get });
  const by = SORT_KEYS.find((key) => key === get("sort"));
  const order = get("order");
  return {
    ...(from && to && from <= to ? { from, to } : {}),
    ...(state.compare ? { compare: "1" } : {}),
    ...(state.unusedOnly ? { activity: "unused" } : {}),
    ...(state.search ? { q: state.search } : {}),
    ...(by ? { sort: by } : {}),
    ...(order === "asc" || order === "desc" ? { order } : {})
  };
}
