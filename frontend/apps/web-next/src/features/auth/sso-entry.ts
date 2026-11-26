import type { Schema } from "@/lib/api/models";
import { safeNextPath } from "@/lib/auth/safe-next";

/**
 * Where the browser starts a sign-in at the identity provider. `mfa` signs in
 * for multi-factor authentication: the provider is asked for it, and only an
 * answer that meets the organisation's rule gives a new session.
 */
export function federationHref(next?: string, tenant?: string, mfa = false): string {
  const search = new URLSearchParams();
  if (tenant) search.set("tenant", tenant);
  if (next) search.set("next", safeNextPath(next));
  if (mfa) search.set("mfa", "true");
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

/**
 * Where a signed-in person signs in again for MFA and comes back to `next`.
 * No organisation is named: the backend asks at the one their session is in.
 */
export function mfaSignInHref(next: string): string {
  return federationHref(next, undefined, true);
}
