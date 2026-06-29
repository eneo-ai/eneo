import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ModelProvider = Schema<"ModelProviderPublic">;
export type ModelProviderUpdate = Schema<"ModelProviderUpdate">;
export type TenantCompletionModelCreate = Schema<"TenantCompletionModelCreate">;

/**
 * The `/capabilities/` endpoint is free-form (`{[key]: unknown}`) in the
 * OpenAPI schema; these interfaces mirror what the backend actually returns
 * (see the Svelte `modelProviderCapabilities`) so we can render the
 * provider-specific credential/config fields with types.
 */
export interface ProviderFieldDef {
  name: string;
  required: boolean;
  secret: boolean;
  in: "credentials" | "config";
}
export interface ProviderCapability {
  modes: string[];
  models: Record<string, unknown[]>;
  fields: ProviderFieldDef[];
}
export interface ProviderCapabilities {
  providers: Record<string, ProviderCapability>;
  default_fields: ProviderFieldDef[];
}

export const PROVIDERS_KEY = ["admin-model-providers"];

export function modelProvidersQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: PROVIDERS_KEY,
    queryFn: (): Promise<ModelProvider[]> => unwrap(api.GET("/api/v1/admin/model-providers/"))
  });
}

export function providerCapabilitiesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-model-provider-capabilities"],
    staleTime: Infinity, // capability metadata is static for a deployment
    queryFn: async (): Promise<ProviderCapabilities> =>
      // The endpoint is typed as a free-form object; shape verified above.
      (await unwrap(
        api.GET("/api/v1/admin/model-providers/capabilities/")
      )) as unknown as ProviderCapabilities
  });
}

export function createProvider(
  api: EneoClient,
  body: {
    name: string;
    provider_type: string;
    credentials: Record<string, string>;
    config: Record<string, string>;
  }
) {
  return unwrap(api.POST("/api/v1/admin/model-providers/", { body }));
}

export function createCompletionModel(api: EneoClient, body: TenantCompletionModelCreate) {
  return unwrap(api.POST("/api/v1/admin/tenant-models/completion/", { body }));
}

/** Update a custom model provider (name / active / credentials). */
export function updateProvider(api: EneoClient, id: string, body: ModelProviderUpdate) {
  return unwrap(
    api.PUT("/api/v1/admin/model-providers/{provider_id}/", {
      params: { path: { provider_id: id } },
      body
    })
  );
}

/** Delete a custom model provider (backend 400s if models are still attached). */
export function deleteProvider(api: EneoClient, id: string) {
  return unwrap(
    api.DELETE("/api/v1/admin/model-providers/{provider_id}/", {
      params: { path: { provider_id: id } }
    })
  );
}

/** Credential/config field definitions for a provider type (with fallback). */
export function providerFields(caps: ProviderCapabilities, type: string): ProviderFieldDef[] {
  return caps.providers[type]?.fields ?? caps.default_fields ?? [];
}

/** Provider types that support completion models, in a stable order. */
export function completionProviderTypes(caps: ProviderCapabilities): string[] {
  return Object.entries(caps.providers)
    .filter(([, capability]) => capability.modes.includes("completion"))
    .map(([type]) => type)
    .sort();
}
