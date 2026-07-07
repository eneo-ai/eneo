import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ModelProvider = Schema<"ModelProviderPublic">;
export type ModelProviderUpdate = Schema<"ModelProviderUpdate">;

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

export function providerFieldLabel(t: (key: string) => string, name: string): string {
  switch (name) {
    case "api_key":
      return t("api_key");
    case "endpoint":
      return t("endpoint_url");
    case "api_version":
      return t("api_version");
    case "deployment_name":
      return t("deployment_name");
    default:
      return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

export function providerConfirmFieldLabel(t: (key: string) => string, name: string): string {
  return name === "api_key" ? t("confirm_api_key") : t("confirm_secret");
}

/** Provider-specific input hint shown inside a field (ported from the Svelte wizard). */
export function providerFieldPlaceholder(
  t: (key: string) => string,
  name: string,
  providerType: string
): string {
  switch (name) {
    case "api_key":
      return t("enter_api_key");
    case "endpoint":
      if (providerType === "azure") return "https://your-resource.openai.azure.com";
      if (providerType === "hosted_vllm") return "https://your-vllm-server.com";
      return "https://api.example.com/v1";
    case "api_version":
      return t("api_version_placeholder");
    case "deployment_name":
      return t("deployment_name_placeholder");
    default:
      return "";
  }
}

/** Provider-specific helper text shown below a field (ported from the Svelte wizard). */
export function providerFieldHint(
  t: (key: string) => string,
  name: string,
  required: boolean,
  providerType: string
): string {
  switch (name) {
    case "api_key":
      return t("will_be_encrypted");
    case "endpoint":
      if (providerType === "azure") return t("endpoint_required_azure");
      if (providerType === "hosted_vllm") return t("endpoint_required_vllm");
      if (!required) return t("endpoint_optional_generic");
      return "";
    case "api_version":
      return t("api_version_required");
    case "deployment_name":
      return t("deployment_name_required");
    default:
      return "";
  }
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
 * Provider types as gallery options, sorted by display name. The wizard can add
 * completion, embedding, and transcription tenant models, so each option keeps
 * its supported mode list for filtering and initial model-type selection.
 */
export function providerOptions(caps: ProviderCapabilities): ProviderOption[] {
  return Object.entries(caps.providers)
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
