import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { SkillRuntimePolicy } from "@/features/admin/skills/skill-runtime-policy";

export type GovernancePolicy = Schema<"GovernancePolicyPublic">;
export type GovernancePolicyUpdate = Schema<"GovernancePolicyUpdate">;
export type ModelProvider = Schema<"ModelProviderPublic">;

export const GOVERNANCE_POLICY_KEY = ["admin-governance-policy"];
export const MODEL_PROVIDERS_KEY = ["admin-model-providers"];
/** Shared with the admin Skills page, which reads the same policy. */
export const SKILL_RUNTIME_POLICY_KEY = ["skill-runtime-policy"];

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

/**
 * The Skill runtime policy the governance page reads for selective
 * activation. The server route prefetches it like the other queries: a
 * suspense query that is not in the dehydrated cache would run on the server
 * with the browser client's relative proxy URL, which fails there.
 */
export function skillRuntimePolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: SKILL_RUNTIME_POLICY_KEY,
    queryFn: (): Promise<SkillRuntimePolicy> =>
      unwrap(api.GET("/api/v1/settings/skills/runtime-policy"))
  });
}
