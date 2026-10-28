import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

/** The organisation's sign-in settings as its admin sees them: never the secret. */
export type FederationView = Schema<"TenantFederationAdminView">;
export type FederationPatch = Schema<"TenantAdminFederationPatch">;

export const FEDERATION_KEY = ["admin", "federation"] as const;

export function federationQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: FEDERATION_KEY,
    queryFn: (): Promise<FederationView> => unwrap(api.GET("/api/v1/admin/federation"))
  });
}

/** Saves an edit made against `body.revision`; the answer is the fresh view. */
export function patchFederation(api: EneoClient, body: FederationPatch): Promise<FederationView> {
  return unwrap(api.PATCH("/api/v1/admin/federation", { body }));
}

/** The page's message for a refusal it explains itself (`EneoApiError.reason`). */
const ERROR_KEYS: Record<string, string> = {
  federation_config_revision_conflict: "federation_admin_conflict_title",
  federation_secret_looks_masked: "federation_admin_secret_masked",
  federation_encryption_unavailable: "federation_admin_encryption_unavailable",
  federation_not_configured: "federation_admin_not_configured_title",
  federation_disabled: "federation_admin_not_configured_title"
};

export function federationErrorKey(reason: string | undefined): string | null {
  return reason ? (ERROR_KEYS[reason] ?? null) : null;
}
