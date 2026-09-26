import {
  formatCostPerMillionTokens,
  formatCostPerMinute,
  getDeprecationStatus
} from "@/features/ai-models/format-model-stats";
import { isApiKeyRequired, type ModelProvider, type ProviderCapabilities } from "./model-providers";
import { type AdminModel, type ModelKind, type ModelsPresentation, modelLabel } from "./models";

export type KindedModel = { model: AdminModel; kind: ModelKind };

/**
 * What the provider data says about a provider: switched off by an admin, a
 * required API key is missing (its models cannot be called), or configured.
 * There is no live connection check behind "ready".
 */
export type ProviderStatus = "ready" | "missing_key" | "inactive";

export interface ProviderSection {
  key: string;
  name: string;
  /** Provider type used for the logo. */
  providerType: string;
  providerId: string;
  provider: ModelProvider;
  maskedKey?: string | null;
  hasKey: boolean;
  isActive: boolean;
  /** A required API key is missing. */
  needsKey: boolean;
  status: ProviderStatus;
  models: KindedModel[];
}

function flatten(presentation: ModelsPresentation): KindedModel[] {
  return [
    ...presentation.completion_models.map((model) => ({ model, kind: "completion" as const })),
    ...presentation.embedding_models.map((model) => ({ model, kind: "embedding" as const })),
    ...presentation.transcription_models.map((model) => ({ model, kind: "transcription" as const }))
  ];
}

/**
 * A required API key is missing. Whether the key is required comes from the
 * backend's field definitions (the capabilities endpoint): self-hosted vLLM,
 * for one, needs none.
 */
function needsKey(provider: ModelProvider, capabilities: ProviderCapabilities): boolean {
  return !provider.masked_api_key && isApiKeyRequired(capabilities, provider.provider_type);
}

export function providerStatus(
  provider: ModelProvider,
  capabilities: ProviderCapabilities
): ProviderStatus {
  if (!provider.is_active) return "inactive";
  return needsKey(provider, capabilities) ? "missing_key" : "ready";
}

/**
 * Group models by the custom provider they belong to. Only provider-backed
 * models are shown (matching the Svelte admin's `provider_id != null` filter) —
 * legacy global/seeded models without a provider are intentionally omitted so a
 * provider isn't duplicated by its orphaned global models.
 */
export function buildProviderSections(
  presentation: ModelsPresentation,
  providers: ModelProvider[],
  capabilities: ProviderCapabilities
): ProviderSection[] {
  const byProvider = new Map<string, KindedModel[]>();
  for (const entry of flatten(presentation)) {
    const providerId = (entry.model as { provider_id?: string | null }).provider_id;
    if (!providerId) continue;
    const list = byProvider.get(providerId) ?? [];
    list.push(entry);
    byProvider.set(providerId, list);
  }

  const sections: ProviderSection[] = providers.map((provider) => {
    const hasKey = Boolean(provider.masked_api_key);
    return {
      key: provider.id,
      name: provider.name,
      providerType: provider.provider_type,
      providerId: provider.id,
      provider,
      maskedKey: provider.masked_api_key,
      hasKey,
      isActive: provider.is_active,
      needsKey: needsKey(provider, capabilities),
      status: providerStatus(provider, capabilities),
      models: byProvider.get(provider.id) ?? []
    };
  });

  // Providers that need a key bubble up, then by model count desc, then name.
  return sections.sort((a, b) => {
    if (a.needsKey !== b.needsKey) return a.needsKey ? -1 : 1;
    if (a.models.length !== b.models.length) return b.models.length - a.models.length;
    return a.name.localeCompare(b.name);
  });
}

export type KindFilter = "all" | ModelKind;
export const KIND_FILTERS: KindFilter[] = ["all", "completion", "embedding", "transcription"];

/** Security filter value for models without a classification. */
export const UNCLASSIFIED = "__unclassified__";

export interface ModelFilters {
  /** Free text; matches provider name, model display name and technical id. */
  search: string;
  kind: KindFilter;
  /** "all", {@link UNCLASSIFIED} or a security classification id. */
  security: string;
}

export function modelClassificationId(model: AdminModel): string | null {
  return (
    (model as { security_classification?: { id: string } | null }).security_classification?.id ??
    null
  );
}

function matchesSecurity(model: AdminModel, security: string): boolean {
  if (security === "all") return true;
  const id = modelClassificationId(model);
  return security === UNCLASSIFIED ? id === null : id === security;
}

function matchesSearch(model: AdminModel, query: string): boolean {
  return `${modelLabel(model)} ${model.name}`.toLowerCase().includes(query);
}

function sectionModels(
  section: ProviderSection,
  { search, kind, security }: ModelFilters
): KindedModel[] {
  const query = search.trim().toLowerCase();
  const nameMatches = query !== "" && section.name.toLowerCase().includes(query);
  return section.models.filter(({ model, kind: modelKind }) => {
    if (kind !== "all" && modelKind !== kind) return false;
    if (!matchesSecurity(model, security)) return false;
    return !query || nameMatches || matchesSearch(model, query);
  });
}

/**
 * Each provider with the models that pass the filters. Providers left with
 * nothing to show (a fresh provider without models, or none of the filtered
 * kind) are dropped; they stay reachable through the add-model wizard.
 */
export function filterSections(
  sections: ProviderSection[],
  filters: ModelFilters
): { section: ProviderSection; models: KindedModel[] }[] {
  return sections
    .map((section) => ({ section, models: sectionModels(section, filters) }))
    .filter((entry) => entry.models.length > 0);
}

/** Model count per type filter, honouring the search and security filters. */
export function countByKind(
  sections: ProviderSection[],
  filters: Omit<ModelFilters, "kind">
): Record<KindFilter, number> {
  const counts: Record<KindFilter, number> = {
    all: 0,
    completion: 0,
    embedding: 0,
    transcription: 0
  };
  for (const section of sections) {
    for (const { kind } of sectionModels(section, { ...filters, kind: "all" })) {
      counts.all += 1;
      counts[kind] += 1;
    }
  }
  return counts;
}

export type ModelLifecycle =
  | { kind: "active" }
  | { kind: "retiring"; date: string }
  | { kind: "deprecated"; date: string | null };

/** Deprecation from the recorded date, or the admin's manual deprecation flag. */
export function modelLifecycle(model: AdminModel, today?: string): ModelLifecycle {
  const status = getDeprecationStatus(model, today);
  if (status.kind === "deprecated") return { kind: "deprecated", date: status.date };
  if (model.is_deprecated) return { kind: "deprecated", date: null };
  if (status.kind === "retiring") return { kind: "retiring", date: status.date };
  return { kind: "active" };
}

export interface ModelsAttention {
  /** Providers whose required API key is missing (their models can't be called). */
  missingKey: ProviderSection[];
  /** Deprecated models that are still enabled and not yet migrated. */
  deprecated: KindedModel[];
}

/** Real problems the provider and model data expose, for the page banner. */
export function modelsAttention(sections: ProviderSection[], today?: string): ModelsAttention {
  const missingKey = sections.filter((section) => section.isActive && section.needsKey);
  const deprecated = sections.flatMap((section) =>
    section.models.filter(
      ({ model }) =>
        model.is_org_enabled === true &&
        !(model as { migrated_to_model_id?: string | null }).migrated_to_model_id &&
        modelLifecycle(model, today).kind === "deprecated"
    )
  );
  return { missingKey, deprecated };
}

export type ModelPrice =
  | { kind: "tokens"; input: string | null; output: string | null }
  | { kind: "minute"; value: string }
  | { kind: "unknown" };

/** Indicative price: per 1M tokens (in / out), or per audio minute for transcription. */
export function modelPrice(model: AdminModel, kind: ModelKind): ModelPrice {
  if (kind === "transcription") {
    const value = formatCostPerMinute(
      (model as { cost_per_minute?: string | null }).cost_per_minute
    );
    return value ? { kind: "minute", value } : { kind: "unknown" };
  }
  const costs = model as {
    input_cost_per_token?: string | null;
    output_cost_per_token?: string | null;
  };
  const input = formatCostPerMillionTokens(costs.input_cost_per_token);
  const output = formatCostPerMillionTokens(costs.output_cost_per_token);
  return input || output ? { kind: "tokens", input, output } : { kind: "unknown" };
}
