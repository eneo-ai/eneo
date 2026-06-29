import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type TokenUsage = Schema<"TokenUsageSummary">;
export type UserTokenUsage = Schema<"UserTokenUsageSummary">;
export type StorageModel = Schema<"StorageModel">;
export type StorageInfo = Schema<"StorageInfoModel">;

export function tokenUsageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-token-usage"],
    queryFn: (): Promise<TokenUsage> => unwrap(api.GET("/api/v1/token-usage/"))
  });
}

/** Per-user token usage (backend defaults to the last 30 days). */
export function userTokenUsageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-user-token-usage"],
    queryFn: (): Promise<UserTokenUsage> => unwrap(api.GET("/api/v1/token-usage/users"))
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
