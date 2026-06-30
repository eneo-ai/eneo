/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Resolve the list of model suggestions for a given provider/mode.
 *
 * Strategy:
 *   1. Always try the provider's live `/v1/models` first — the backend
 *      enriches each entry with capability metadata from litellm.model_cost.
 *   2. If the response is empty or fails, fall back to the static LiteLLM
 *      catalog shipped via the capabilities endpoint.
 *   3. Some providers (Azure) cannot list models at all; we skip both.
 */
import type { Eneo } from "@eneo/eneo-js";
import {
  NO_SUGGESTIONS_PROVIDERS,
  type ModelProviderCapabilities
} from "../../modelProviderCapabilities";
import type { ModelInfo, ModelType } from "./draft";

const MODE_MAP: Record<ModelType, string> = {
  completion: "completion",
  embedding: "embedding",
  transcription: "transcription"
};

export interface LoadResult {
  models: ModelInfo[];
  error: string | null;
}

export async function loadLiveModels(
  eneo: Eneo,
  providerId: string,
  modelType: ModelType
): Promise<LoadResult> {
  try {
    const result = (await eneo.modelProviders.listModels({
      id: providerId,
      mode: MODE_MAP[modelType] as "completion" | "embedding" | "transcription"
    })) as unknown as Record<string, unknown>[];

    if (!Array.isArray(result)) {
      return { models: [], error: null };
    }

    const first = result[0] as Record<string, unknown> | undefined;
    if (first?.error) {
      return { models: [], error: String(first.error) };
    }

    const models: ModelInfo[] = result.map((item) => ({
      name: String(item.name),
      display_name: item.display_name != null ? String(item.display_name) : undefined,
      mode: item.mode != null ? String(item.mode) : undefined,
      max_input_tokens: item.max_input_tokens as number | undefined,
      max_output_tokens: item.max_output_tokens as number | undefined,
      supports_vision: (item.supports_vision as boolean | undefined) ?? false,
      supports_function_calling: (item.supports_function_calling as boolean | undefined) ?? false,
      supports_reasoning: (item.supports_reasoning as boolean | undefined) ?? false,
      output_vector_size: item.output_vector_size as number | undefined,
      // Pass cost fields through. The backend returns numbers (or null);
      // ModelDraftForm.applyCatalogModelToDraft handles missing values.
      input_cost_per_token: item.input_cost_per_token as number | null | undefined,
      output_cost_per_token: item.output_cost_per_token as number | null | undefined,
      cost_per_minute: item.cost_per_minute as number | null | undefined
    }));

    return { models, error: null };
  } catch {
    return { models: [], error: "Could not fetch models from provider" };
  }
}

export function staticCatalog(
  capabilities: ModelProviderCapabilities | null,
  providerType: string,
  modelType: ModelType
): ModelInfo[] {
  if (NO_SUGGESTIONS_PROVIDERS.has(providerType)) return [];
  if (!capabilities) return [];
  const cap = capabilities.providers[providerType];
  if (!cap) return [];
  return (cap.models[MODE_MAP[modelType]] ?? []) as ModelInfo[];
}

export function providerSupportsMode(
  capabilities: ModelProviderCapabilities | null,
  providerType: string,
  modelType: ModelType
): "supported" | "unsupported" | "unknown" {
  if (!capabilities) return "unknown";
  if (Object.keys(capabilities.providers).length === 0) return "unknown";
  const cap = capabilities.providers[providerType];
  if (!cap) return "unknown";
  return cap.modes?.includes(MODE_MAP[modelType]) ? "supported" : "unsupported";
}

export function isSelfHostedProvider(
  capabilities: ModelProviderCapabilities | null,
  providerType: string
): boolean {
  if (!capabilities) return false;
  const cap = capabilities.providers[providerType];
  if (!cap) return false;
  return Object.keys(cap.models ?? {}).length === 0;
}

// Re-exported so `ModelSuggestions` and other in-folder consumers don't have
// to reach across to `$lib/features/ai-models`. The canonical implementation
// lives in `formatModelStats.ts`.
export { formatTokens } from "$lib/features/ai-models/formatModelStats";
