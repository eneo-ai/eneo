import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type TokenUsage = Schema<"TokenUsageSummary">;
export type StorageModel = Schema<"StorageModel">;
export type StorageInfo = Schema<"StorageInfoModel">;

export function tokenUsageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-token-usage"],
    queryFn: (): Promise<TokenUsage> => unwrap(api.GET("/api/v1/token-usage/"))
  });
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
