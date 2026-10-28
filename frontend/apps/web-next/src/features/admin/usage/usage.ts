import { calendarDate } from "@/lib/calendar-date";
import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type TokenUsage = Schema<"TokenUsageSummary">;
export type UserTokenUsage = Schema<"UserTokenUsageSummary">;
export type UserTokenUsageDetail = Schema<"UserTokenUsageSummaryDetail">;
export type StorageModel = Schema<"StorageModel">;
export type StorageInfo = Schema<"StorageInfoModel">;
export type UserUsageRow = Schema<"UserTokenUsage">;

export type UsageRange = { from: string; to: string };

function dateInput(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function defaultUsageRange(now = new Date()): UsageRange {
  const start = new Date(now);
  start.setDate(start.getDate() - 30);
  return { from: dateInput(start), to: dateInput(now) };
}

export function usageRangeFromSearchParams(
  searchParams: Record<string, string | string[] | undefined>,
  fallback = defaultUsageRange()
): UsageRange {
  const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);
  const from = calendarDate(first(searchParams.from));
  const to = calendarDate(first(searchParams.to));
  if (!from || !to || from > to) return fallback;
  return { from, to };
}

export function usageRangeQuery(range: UsageRange): { start_date: string; end_date: string } {
  return {
    start_date: new Date(`${range.from}T00:00:00`).toISOString(),
    end_date: new Date(`${range.to}T23:59:59`).toISOString()
  };
}

/** Tenant token usage per model; by default the last 30 days, the page's overview. */
export function tokenUsageQueryOptions(api: EneoClient, range = defaultUsageRange()) {
  return queryOptions({
    queryKey: ["admin-token-usage", range],
    queryFn: (): Promise<TokenUsage> =>
      unwrap(api.GET("/api/v1/token-usage/", { params: { query: usageRangeQuery(range) } }))
  });
}

export type UserSortBy = Schema<"UserSortBy">;
export type SortOrder = "asc" | "desc";

/** One page of the users list, as apps/web asks for it (usage-query.ts). */
export type UserUsageQuery = {
  page: number;
  sortBy: UserSortBy;
  sortOrder: SortOrder;
  /** Trimmed; empty means no search. */
  search: string;
};

export const USER_USAGE_PAGE_SIZE = 25;

/** Per-user token usage, searched, sorted and paged on the server. */
export function userTokenUsageQueryOptions(
  api: EneoClient,
  range: UsageRange,
  query: UserUsageQuery
) {
  return queryOptions({
    queryKey: ["admin-user-token-usage", range, query],
    queryFn: (): Promise<UserTokenUsage> =>
      unwrap(
        api.GET("/api/v1/token-usage/users", {
          params: {
            query: {
              ...usageRangeQuery(range),
              page: query.page,
              per_page: USER_USAGE_PAGE_SIZE,
              sort_by: query.sortBy,
              sort_order: query.sortOrder,
              search: query.search || undefined
            }
          }
        })
      )
  });
}

export const USAGE_TABS = ["tokens", "users", "storage"] as const;
export type UsageTab = (typeof USAGE_TABS)[number];

/** What the usage page shows; it lives in the URL so a reload or a user's page leads back to it. */
export type UsageView = UserUsageQuery & { tab: UsageTab; range: UsageRange };

const USER_SORT_FIELDS: UserSortBy[] = [
  "username",
  "input_tokens",
  "output_tokens",
  "total_tokens",
  "requests"
];
/** The backend rejects longer searches. */
export const MAX_SEARCH_LENGTH = 200;

/** The view a URL asks for; anything malformed falls back to its default. */
export function readUsageView(
  params: Pick<URLSearchParams, "get">,
  fallbackRange = defaultUsageRange()
): UsageView {
  const page = Number(params.get("page") || "1");
  return {
    tab: USAGE_TABS.find((tab) => tab === params.get("tab")) ?? "tokens",
    range: usageRangeFromSearchParams(
      { from: params.get("from") ?? undefined, to: params.get("to") ?? undefined },
      fallbackRange
    ),
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    sortBy: USER_SORT_FIELDS.find((field) => field === params.get("sortBy")) ?? "total_tokens",
    sortOrder: params.get("sortOrder") === "asc" ? "asc" : "desc",
    search: (params.get("userSearch") ?? "").trim().slice(0, MAX_SEARCH_LENGTH)
  };
}

/**
 * The query string (`?…`, or "" when nothing is left) for `view`, written
 * over `current`: other parameters stay, and defaults are left out.
 */
export function usageViewSearch(
  view: UsageView,
  current = "",
  defaultRange = defaultUsageRange()
): string {
  const params = new URLSearchParams(current);
  const isDefaultRange = view.range.from === defaultRange.from && view.range.to === defaultRange.to;
  const entries: [string, string, boolean][] = [
    ["tab", view.tab, view.tab === "tokens"],
    ["from", view.range.from, isDefaultRange],
    ["to", view.range.to, isDefaultRange],
    ["page", String(view.page), view.page === 1],
    ["sortBy", view.sortBy, view.sortBy === "total_tokens"],
    ["sortOrder", view.sortOrder, view.sortOrder === "desc"],
    ["userSearch", view.search, view.search === ""]
  ];
  for (const [key, value, isDefault] of entries) {
    if (isDefault) params.delete(key);
    else params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** The usage page with the view a user's page was opened from (its URL carries it). */
export function usageListHref(params: Pick<URLSearchParams, "get">): string {
  return `/admin/usage${usageViewSearch(readUsageView(params))}`;
}

export function userTokenUsageSummaryQueryOptions(
  api: EneoClient,
  userId: string,
  range: UsageRange
) {
  return queryOptions({
    queryKey: ["admin-user-token-usage-summary", userId, range],
    queryFn: (): Promise<UserTokenUsageDetail> =>
      unwrap(
        api.GET("/api/v1/token-usage/users/{user_id}/summary", {
          params: { path: { user_id: userId }, query: usageRangeQuery(range) }
        })
      )
  });
}

export function userModelBreakdownQueryOptions(api: EneoClient, userId: string, range: UsageRange) {
  return queryOptions({
    queryKey: ["admin-user-token-usage-models", userId, range],
    queryFn: (): Promise<TokenUsage> =>
      unwrap(
        api.GET("/api/v1/token-usage/users/{user_id}", {
          params: { path: { user_id: userId }, query: usageRangeQuery(range) }
        })
      )
  });
}

export type CostRate = { input: number | null; output: number | null };

/** Build a model-id → per-token cost map from the ai-models ratecard. */
export function buildRateMap(
  models: {
    id: string;
    input_cost_per_token?: string | null;
    output_cost_per_token?: string | null;
  }[]
): Map<string, CostRate> {
  const map = new Map<string, CostRate>();
  for (const model of models) {
    map.set(model.id, {
      input: model.input_cost_per_token != null ? Number(model.input_cost_per_token) : null,
      output: model.output_cost_per_token != null ? Number(model.output_cost_per_token) : null
    });
  }
  return map;
}

/** Estimated USD cost for token counts, or null when no rate is known. */
export function estimateCost(
  inputTokens: number,
  outputTokens: number,
  rate: CostRate | undefined
): number | null {
  if (!rate || (rate.input == null && rate.output == null)) return null;
  return inputTokens * (rate.input ?? 0) + outputTokens * (rate.output ?? 0);
}

export function userUsageCost(
  user: Pick<UserUsageRow, "models_used">,
  rates: Map<string, CostRate>
): number | null {
  let total: number | null = null;
  for (const model of user.models_used) {
    const cost = estimateCost(
      model.input_token_usage,
      model.output_token_usage,
      rates.get(model.model_id)
    );
    if (cost != null) total = (total ?? 0) + cost;
  }
  return total;
}

export type UsageIntensity = "low" | "medium" | "high";

/** Days from the range's start to its end (at least 1), as apps/web scales its thresholds. */
export function usageRangeDayCount(range: UsageRange): number {
  const start = new Date(`${range.from}T00:00:00`).getTime();
  const end = new Date(`${range.to}T00:00:00`).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 30;
  return Math.max(1, Math.round((end - start) / 86_400_000));
}

/** Token totals above which a user's usage is high or medium: 500k and 50k per 30 days. */
export function usageThresholds(range: UsageRange): { high: number; medium: number } {
  const scale = usageRangeDayCount(range) / 30;
  return { high: Math.round(500_000 * scale), medium: Math.round(50_000 * scale) };
}

export function usageIntensity(totalTokens: number, range: UsageRange): UsageIntensity {
  const { high, medium } = usageThresholds(range);
  if (totalTokens > high) return "high";
  if (totalTokens > medium) return "medium";
  return "low";
}

export function formatCost(amount: number | null): string {
  if (amount == null) return "–";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: amount > 0 && amount < 1 ? 4 : 2
  }).format(amount);
}
export function storageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-storage"],
    queryFn: (): Promise<StorageModel> => unwrap(api.GET("/api/v1/storage/"))
  });
}
export function storageSpacesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-storage-spaces"],
    queryFn: (): Promise<StorageInfo> => unwrap(api.GET("/api/v1/storage/spaces/"))
  });
}
