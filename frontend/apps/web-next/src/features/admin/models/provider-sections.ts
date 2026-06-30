import type { ModelProvider } from "./model-providers";
import type { AdminModel, ModelKind, ModelsPresentation } from "./models";

export type KindedModel = { model: AdminModel; kind: ModelKind };

export interface ProviderSection {
  key: string;
  name: string;
  /** Provider type used for the logo. */
  providerType: string;
  providerId: string;
  maskedKey?: string | null;
  hasKey: boolean;
  isActive: boolean;
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
 * Group models by the custom provider they belong to. Only provider-backed
 * models are shown (matching the Svelte admin's `provider_id != null` filter) —
 * legacy global/seeded models without a provider are intentionally omitted so a
 * provider isn't duplicated by its orphaned global models.
 */
export function buildProviderSections(
  presentation: ModelsPresentation,
  providers: ModelProvider[]
): ProviderSection[] {
  const byProvider = new Map<string, KindedModel[]>();
  for (const entry of flatten(presentation)) {
    const providerId = (entry.model as { provider_id?: string | null }).provider_id;
    if (!providerId) continue;
    const list = byProvider.get(providerId) ?? [];
    list.push(entry);
    byProvider.set(providerId, list);
  }

  const sections: ProviderSection[] = providers.map((provider) => ({
    key: provider.id,
    name: provider.name,
    providerType: provider.provider_type,
    providerId: provider.id,
    maskedKey: provider.masked_api_key,
    hasKey: Boolean(provider.masked_api_key),
    isActive: provider.is_active,
    models: byProvider.get(provider.id) ?? []
  }));

  // Providers that need a key bubble up, then by model count desc, then name.
  return sections.sort((a, b) => {
    if (a.hasKey !== b.hasKey) return a.hasKey ? 1 : -1;
    if (a.models.length !== b.models.length) return b.models.length - a.models.length;
    return a.name.localeCompare(b.name);
  });
}
