import type { Schema } from "@/lib/api/models";
import { safeNextPath } from "@/lib/auth/safe-next";

export function federationHref(next?: string, tenant?: string): string {
  const search = new URLSearchParams();
  if (tenant) search.set("tenant", tenant);
  if (next) search.set("next", safeNextPath(next));
  return `/api/v1/auth/browser/initiate${search.size ? `?${search}` : ""}`;
}

export function ssoEntry(
  status: Schema<"FederationStatusResponse"> | null | undefined,
  next?: string
): string | null {
  return status &&
    !status.has_multi_tenant_federation &&
    (status.has_global_oidc_config || status.has_single_tenant_federation)
    ? federationHref(next)
    : null;
}
