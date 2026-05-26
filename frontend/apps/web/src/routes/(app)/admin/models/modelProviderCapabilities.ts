/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Centralised provider/capability metadata.
 *
 * The backend exposes a `/capabilities` endpoint that lists every supported
 * provider, the mode(s) it supports (completion / embedding / transcription),
 * the field definitions needed to authenticate against it, and a static
 * fallback model catalog. This module owns:
 *
 *  1. The cached fetch (`getModelProviderCapabilities`).
 *  2. The presentation helpers (labels, placeholders, hints, default hosting)
 *     that previously lived duplicated across StepCredentials, StepModels and
 *     ProviderDialog.
 *
 * Add a new provider on the backend and it will appear here automatically;
 * only display-name overrides need a code change.
 */
import type { Intric } from "@intric/intric-js";
import { m } from "$lib/paraglide/messages";

export interface ModelProviderFieldDef {
  name: string;
  required: boolean;
  secret: boolean;
  in: "credentials" | "config";
}

export type CapabilityModel = string | { name?: string; [key: string]: unknown };

export interface ModelProviderCapability {
  modes: string[];
  models: Record<string, CapabilityModel[]>;
  fields: ModelProviderFieldDef[];
}

export interface ModelProviderCapabilities {
  providers: Record<string, ModelProviderCapability>;
  default_fields: ModelProviderFieldDef[];
}

let capabilitiesCache: ModelProviderCapabilities | null = null;
let capabilitiesPromise: Promise<ModelProviderCapabilities> | null = null;

export async function getModelProviderCapabilities(
  intric: Intric
): Promise<ModelProviderCapabilities> {
  if (capabilitiesCache) {
    return capabilitiesCache;
  }

  if (!capabilitiesPromise) {
    capabilitiesPromise = intric.modelProviders
      .getCapabilities()
      .then((capabilities) => {
        capabilitiesCache = capabilities as ModelProviderCapabilities;
        return capabilitiesCache;
      })
      .catch((error) => {
        capabilitiesPromise = null;
        throw error;
      });
  }

  return capabilitiesPromise;
}

// --- Presentation helpers --------------------------------------------------

/**
 * Display-name overrides for known providers. Falls back to a humanised
 * version of the raw type. Drop this map once the backend ships labels.
 */
const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  azure: "Azure OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  cohere: "Cohere",
  mistral: "Mistral AI",
  hosted_vllm: "vLLM"
};

export function formatProviderLabel(type: string): string {
  if (!type) return "";
  return PROVIDER_LABELS[type] ?? type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Localised label for a credential/config field. Unknown field names are
 * humanised so a backend-only addition doesn't break the UI.
 */
export function formatFieldLabel(name: string): string {
  switch (name) {
    case "api_key":
      return m.api_key();
    case "endpoint":
      return m.endpoint_url();
    case "api_version":
      return m.api_version();
    case "deployment_name":
      return m.deployment_name();
    default:
      return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

export function getFieldPlaceholder(name: string, providerType: string): string {
  if (name === "api_key") return m.enter_api_key();
  if (name === "endpoint") {
    if (providerType === "azure") return "https://your-resource.openai.azure.com";
    if (providerType === "hosted_vllm") return "https://your-vllm-server.com";
    return "https://api.example.com/v1";
  }
  if (name === "api_version") return m.api_version_placeholder();
  if (name === "deployment_name") return m.deployment_name_placeholder();
  return "";
}

export function getFieldHint(
  name: string,
  required: boolean,
  providerType: string,
  context: "create" | "edit" = "create"
): string {
  if (name === "api_key") return context === "create" ? m.will_be_encrypted() : "";
  if (name === "endpoint") {
    if (providerType === "openai" && context === "edit") return m.endpoint_optional_openai();
    if (providerType === "azure") return m.endpoint_required_azure();
    if (providerType === "hosted_vllm") return m.endpoint_required_vllm();
    if (!required && context === "edit") return m.endpoint_optional_default();
    if (!required) return m.endpoint_optional_generic();
  }
  if (name === "api_version") return m.api_version_required();
  if (name === "deployment_name") return m.deployment_name_required();
  return "";
}

/**
 * Default hosting region per provider. Used when seeding the Add-Model form;
 * the user can always override via the hosting select.
 */
export const PROVIDER_DEFAULT_HOSTING: Record<string, string> = {
  openai: "usa",
  anthropic: "usa",
  gemini: "usa",
  google: "usa",
  cohere: "can",
  mistral: "fra",
  deepseek: "chn",
  ai21: "isr",
  friendliai: "kor",
  aleph_alpha: "deu",
  nscale: "gbr",
  zhipuai: "chn",
  moonshot: "chn",
  baidu: "chn",
  volcengine: "chn"
};

/**
 * Providers where neither the live `/v1/models` endpoint nor the static
 * catalog can produce useful suggestions. Azure is the obvious case — its
 * "models" are deployment names that vary per tenant.
 */
export const NO_SUGGESTIONS_PROVIDERS: ReadonlySet<string> = new Set(["azure"]);

/**
 * Resolve the field definitions to render for a given provider type. Falls
 * back to the catalog default when capabilities haven't loaded yet so the
 * form can render optimistically.
 */
export function resolveProviderFields(
  capabilities: ModelProviderCapabilities | null,
  providerType: string
): ModelProviderFieldDef[] {
  const FALLBACK: ModelProviderFieldDef[] = [
    { name: "api_key", required: true, secret: true, in: "credentials" },
    { name: "endpoint", required: false, secret: false, in: "config" }
  ];
  if (!capabilities) return FALLBACK;
  const cap = capabilities.providers[providerType];
  return cap?.fields ?? capabilities.default_fields ?? FALLBACK;
}

/**
 * Build a sorted, labelled list of all known provider types. Used by the
 * "Create new provider" picker.
 */
export function listProviderOptions(
  capabilities: ModelProviderCapabilities | null
): Array<{ value: string; label: string }> {
  if (!capabilities) {
    return Object.keys(PROVIDER_LABELS)
      .map((value) => ({ value, label: formatProviderLabel(value) }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }
  return Object.keys(capabilities.providers)
    .map((value) => ({ value, label: formatProviderLabel(value) }))
    .sort((a, b) => a.label.localeCompare(b.label));
}
