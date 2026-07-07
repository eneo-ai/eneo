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

const DATE_INPUT_RE = /^\d{4}-\d{2}-\d{2}$/;

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
  const from = first(searchParams.from);
  const to = first(searchParams.to);
  if (!from?.match(DATE_INPUT_RE) || !to?.match(DATE_INPUT_RE)) return fallback;
  return { from, to };
}

export function usageRangeQuery(range: UsageRange): { start_date: string; end_date: string } {
  return {
    start_date: new Date(`${range.from}T00:00:00`).toISOString(),
    end_date: new Date(`${range.to}T23:59:59`).toISOString()
  };
}

export function tokenUsageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-token-usage"],
    queryFn: (): Promise<TokenUsage> => unwrap(api.GET("/api/v1/token-usage/"))
  });
}

/** Per-user token usage (backend defaults to the last 30 days). */
export function userTokenUsageQueryOptions(api: EneoClient, range?: UsageRange) {
  return queryOptions({
    queryKey: ["admin-user-token-usage", range],
    queryFn: (): Promise<UserTokenUsage> =>
      unwrap(
        api.GET("/api/v1/token-usage/users", {
          params: {
            query: range ? usageRangeQuery(range) : {}
          }
        })
      )
  });
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

export function usageRangeDayCount(range: UsageRange): number {
  const start = new Date(`${range.from}T00:00:00`).getTime();
  const end = new Date(`${range.to}T00:00:00`).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 30;
  return Math.max(1, Math.round((end - start) / 86_400_000) + 1);
}

export function usageIntensity(totalTokens: number, range: UsageRange): UsageIntensity {
  const scale = usageRangeDayCount(range) / 30;
  if (totalTokens > Math.round(500_000 * scale)) return "high";
  if (totalTokens > Math.round(50_000 * scale)) return "medium";
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
