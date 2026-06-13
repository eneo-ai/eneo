import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type CredentialInfo =
  Schema<"intric__tenants__presentation__tenant_self_credentials_router__CredentialInfo">;
export type SetCredentialRequest =
  Schema<"intric__tenants__presentation__tenant_self_credentials_router__SetCredentialRequest">;

/** Providers that accept a tenant-managed API credential (matches the PUT enum). */
export const CREDENTIAL_PROVIDERS = [
  "openai",
  "anthropic",
  "azure",
  "mistral",
  "ovhcloud",
  "gemini",
  "cohere"
] as const;
export type CredentialProvider = (typeof CREDENTIAL_PROVIDERS)[number];

/** Azure needs the deployment endpoint/version on top of the key. */
export const AZURE_PROVIDER: CredentialProvider = "azure";

export const CREDENTIALS_KEY = ["admin-credentials"];

export function credentialsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: CREDENTIALS_KEY,
    queryFn: async (): Promise<CredentialInfo[]> =>
      (await unwrap(api.GET("/api/v1/admin/credentials/"))).credentials
  });
}

export function setCredential(
  api: EneoClient,
  provider: CredentialProvider,
  body: SetCredentialRequest
) {
  return unwrap(
    api.PUT("/api/v1/admin/credentials/{provider}", { params: { path: { provider } }, body })
  );
}

export function providerDisplayName(provider: string): string {
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}
