import { calendarDate, type IsoDate } from "@/lib/calendar-date";
import { insightRangeOfDays, type InsightRange } from "@/features/insights/insights-range";

export type AssistantInsightView = {
  range: InsightRange;
  includeFollowups: boolean;
  tab: "chat" | "questions";
};

/** One parser for direct links, navigation and the page's visible filters. */
export function readAssistantInsightView(
  params: Pick<URLSearchParams, "get">,
  fallback = insightRangeOfDays(30)
): AssistantInsightView {
  const from = calendarDate(params.get("from"));
  const to = calendarDate(params.get("to"));
  return {
    range: from && to && from <= to ? { start: from as IsoDate, end: to as IsoDate } : fallback,
    includeFollowups: params.get("followups") !== "false",
    tab: params.get("tab") === "questions" ? "questions" : "chat"
  };
}

export function assistantInsightViewSearch(view: AssistantInsightView, current = ""): string {
  const params = new URLSearchParams(current);
  params.set("from", view.range.start);
  params.set("to", view.range.end);
  params.set("followups", String(view.includeFollowups));
  params.set("tab", view.tab);
  return `?${params.toString()}`;
}

/** Router search values are flat strings (or repeated strings), just like URLSearchParams. */
export function validateAssistantInsightSearch(
  search: Record<string, unknown>,
  fallback = insightRangeOfDays(30)
) {
  const view = readAssistantInsightView(
    {
      get: (key) => {
        const value = search[key];
        const first = Array.isArray(value) ? value[0] : value;
        return typeof first === "string" ? first : null;
      }
    },
    fallback
  );
  return {
    from: view.range.start,
    to: view.range.end,
    followups: String(view.includeFollowups),
    tab: view.tab
  };
}
