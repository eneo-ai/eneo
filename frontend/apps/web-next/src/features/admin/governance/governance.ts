import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type GovernancePolicy = Schema<"GovernancePolicyPublic">;
export type GovernancePolicyUpdate = Schema<"GovernancePolicyUpdate">;
export type ModelProvider = Schema<"ModelProviderPublic">;

export const GOVERNANCE_POLICY_KEY = ["admin-governance-policy"];
export const MODEL_PROVIDERS_KEY = ["admin-model-providers"];

export function governancePolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: GOVERNANCE_POLICY_KEY,
    queryFn: (): Promise<GovernancePolicy> => unwrap(api.GET("/api/v1/admin/governance-policy/"))
  });
}

export function modelProvidersQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: MODEL_PROVIDERS_KEY,
    queryFn: (): Promise<ModelProvider[]> => unwrap(api.GET("/api/v1/admin/model-providers/"))
  });
}
