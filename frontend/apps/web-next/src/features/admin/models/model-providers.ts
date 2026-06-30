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

const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  openai: "OpenAI",
  azure: "Azure OpenAI",
  azure_ai_foundry: "Azure AI Foundry",
  anthropic: "Anthropic",
  mistral: "Mistral",
  gemini: "Google Gemini",
  vertex_ai: "Vertex AI",
  bedrock: "AWS Bedrock",
  bedrock_converse: "AWS Bedrock",
  aws: "AWS",
  cohere: "Cohere",
  groq: "Groq",
  ollama: "Ollama",
  hosted_vllm: "vLLM",
  vllm: "vLLM",
  deepseek: "DeepSeek",
  together_ai: "Together AI",
  ovhcloud: "OVHcloud",
  xai: "xAI",
  perplexity: "Perplexity",
  fireworks_ai: "Fireworks AI",
  openrouter: "OpenRouter",
  cerebras: "Cerebras",
  sambanova: "SambaNova",
  replicate: "Replicate",
  huggingface: "Hugging Face",
  meta_llama: "Meta Llama",
  nvidia_nim: "NVIDIA NIM",
  nvidia_triton: "NVIDIA Triton",
  moonshot: "Moonshot AI",
  qwen: "Qwen",
  minimax: "MiniMax",
  voyage: "Voyage AI",
  jina: "Jina AI",
  watsonx: "IBM watsonx",
  snowflake: "Snowflake",
  databricks: "Databricks",
  cloudflare: "Cloudflare",
  xinference: "Xinference"
};

const ACRONYMS = new Set(["ai", "api", "llm", "vllm", "nim", "pse", "sap", "aws", "ibm"]);

/**
 * Friendly provider name. Prefers a curated label, else humanizes the raw
 * `provider_type` ("together_ai" → "Together AI"), upper-casing known acronyms.
 */
export function providerDisplayName(provider: string): string {
  const known = PROVIDER_DISPLAY_NAMES[provider];
  if (known) return known;
  return provider
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) =>
      ACRONYMS.has(word.toLowerCase())
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1)
    )
    .join(" ");
}

/** Provider types that run on the tenant's own infrastructure (vs. a cloud API). */
export const SELF_HOSTED_PROVIDERS = new Set([
  "hosted_vllm",
  "vllm",
  "ollama",
  "xinference",
  "nvidia_triton",
  "nvidia_nim",
  "infinity"
]);

export interface ProviderOption {
  type: string;
  name: string;
  modes: string[];
  selfHosted: boolean;
}

/**
 * Completion-capable provider types as gallery options, sorted by display name.
 * The add-model wizard only creates completion models, so the picker mirrors the
 * old `completionProviderTypes` filter while carrying each provider's modes
 * (for capability badges/filtering) and self-hosted flag.
 */
export function providerOptions(caps: ProviderCapabilities): ProviderOption[] {
  return Object.entries(caps.providers)
    .filter(([, capability]) => capability.modes.includes("completion"))
    .map(([type, capability]) => ({
      type,
      name: providerDisplayName(type),
      modes: capability.modes,
      selfHosted: SELF_HOSTED_PROVIDERS.has(type)
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export const FAVORITES_KEY = ["admin-model-provider-favorites"];

/** Tenant-pinned provider types, surfaced first in the add-provider picker. */
export function favoriteProvidersQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: FAVORITES_KEY,
    queryFn: async (): Promise<string[]> => {
      const data = await unwrap(api.GET("/api/v1/admin/model-providers/favorites/"));
      return data.providers ?? [];
    }
  });
}

/** Replace the tenant's full favorites list (the endpoint is a full overwrite). */
export function setFavoriteProviders(api: EneoClient, providers: string[]) {
  return unwrap(api.PUT("/api/v1/admin/model-providers/favorites/", { body: { providers } }));
}
