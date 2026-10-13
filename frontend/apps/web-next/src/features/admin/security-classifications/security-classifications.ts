import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type SecurityClassification = Schema<"SecurityClassificationPublic">;
export type SecurityClassificationResponse = Schema<"SecurityClassificationResponse">;

export const SECURITY_CLASSIFICATIONS_KEY = ["security-classifications"];

export function securityClassificationsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: SECURITY_CLASSIFICATIONS_KEY,
    queryFn: (): Promise<SecurityClassificationResponse> =>
      unwrap(api.GET("/api/v1/security-classifications/"))
  });
}

/**
 * The backend returns classifications least-secure first (security_level
 * ascending); the UI lists them highest-secure first.
 */
export function highestFirst(classifications: SecurityClassification[]): SecurityClassification[] {
  return [...classifications].sort((a, b) => b.security_level - a.security_level);
}
