import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { ModelKind } from "./models";
import type { ProviderCapabilities } from "./model-providers";

/**
 * Normalized model suggestion used by the add-model wizard. Mirrors the Svelte
 * `ModelInfo` shape so the live `/models` fetch, the static capability catalog
 * and the LiteLLM `model-defaults` lookup all feed the same UI.
 */
export interface CatalogModel {
  name: string;
  display_name?: string;
  mode?: string;
  max_input_tokens?: number;
  max_output_tokens?: number;
  supports_vision: boolean;
  supports_function_calling: boolean;
  supports_reasoning: boolean;
  output_vector_size?: number;
  // USD per token. Backend returns numbers (or null); null = not tracked.
  input_cost_per_token?: number | null;
  output_cost_per_token?: number | null;
  cost_per_minute?: number | null;
}

/** Providers whose API can't enumerate models (Azure lists deployments, not models). */
export const NO_SUGGESTIONS_PROVIDERS = new Set(["azure"]);

function num(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}
function cost(value: unknown): number | null | undefined {
  if (value === null) return null;
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "") return Number(value);
  return undefined;
}

function mapCatalogModel(item: Record<string, unknown>): CatalogModel {
  return {
    name: String(item.name),
    display_name: item.display_name != null ? String(item.display_name) : undefined,
    mode: item.mode != null ? String(item.mode) : undefined,
    max_input_tokens: num(item.max_input_tokens),
    max_output_tokens: num(item.max_output_tokens),
    supports_vision: (item.supports_vision as boolean | undefined) ?? false,
    supports_function_calling: (item.supports_function_calling as boolean | undefined) ?? false,
    supports_reasoning: (item.supports_reasoning as boolean | undefined) ?? false,
    output_vector_size: num(item.output_vector_size),
    input_cost_per_token: cost(item.input_cost_per_token),
    output_cost_per_token: cost(item.output_cost_per_token),
    cost_per_minute: cost(item.cost_per_minute)
  };
}

export interface CatalogResult {
  models: CatalogModel[];
  error: string | null;
}

/**
 * Live model list from a custom provider's API (enriched with LiteLLM
 * capability + cost metadata by the backend). Returns an error string instead
 * of throwing so the wizard can fall back to the static catalog gracefully.
 */
export async function listProviderModels(
  api: EneoClient,
  providerId: string,
  mode: ModelKind
): Promise<CatalogResult> {
  try {
    const result = (await unwrap(
      api.GET("/api/v1/admin/model-providers/{provider_id}/models/", {
        params: { path: { provider_id: providerId }, query: { mode } }
      })
    )) as Record<string, unknown>[];

    if (!Array.isArray(result)) return { models: [], error: null };
    const first = result[0];
    if (first?.error) return { models: [], error: String(first.error) };

    return { models: result.map(mapCatalogModel), error: null };
  } catch {
    return { models: [], error: "provider_models_fetch_failed" };
  }
}

/** Static, bundled catalog for a provider type (from the capabilities endpoint). */
export function staticCatalogModels(
  caps: ProviderCapabilities | undefined,
  providerType: string,
  mode: ModelKind
): CatalogModel[] {
  if (NO_SUGGESTIONS_PROVIDERS.has(providerType)) return [];
  const capability = caps?.providers[providerType];
  if (!capability) return [];
  const models = (capability.models[mode] ?? []) as Record<string, unknown>[];
  return models.map(mapCatalogModel);
}

/**
 * LiteLLM-backed defaults for a single model id — used to enrich a manually
 * typed model, or a built-in provider's pick that has no live `/models` feed.
 */
export async function getModelDefaults(
  api: EneoClient,
  modelName: string,
  providerType?: string
): Promise<CatalogModel | null> {
  try {
    const result = (await unwrap(
      api.GET("/api/v1/admin/model-providers/model-defaults/", {
        params: { query: { model_name: modelName, provider_type: providerType ?? null } }
      })
    )) as Record<string, unknown>;
    if (!result || typeof result !== "object" || result.error) return null;
    return mapCatalogModel({ name: modelName, ...result });
  } catch {
    return null;
  }
}
