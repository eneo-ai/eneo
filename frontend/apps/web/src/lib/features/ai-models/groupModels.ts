import type { CompletionModel } from "@intric/intric-js";

export type ModelGroup = {
  id: string | null;
  label: string;
  providerType: string | null;
  models: CompletionModel[];
};

/**
 * Groups completion models by their provider.
 * System models (provider_id === null) are placed in a separate group at the top.
 * Provider groups are sorted alphabetically by provider name.
 * Models within each group are sorted by nickname.
 */
export function groupModelsByProvider(
  models: CompletionModel[],
  systemModelsLabel: string
): ModelGroup[] {
  const systemModels: CompletionModel[] = [];
  const providerMap = new Map<
    string,
    { name: string; type: string | null; models: CompletionModel[] }
  >();

  for (const model of models) {
    if (!model.provider_id) {
      systemModels.push(model);
    } else {
      const providerId = model.provider_id;
      if (!providerMap.has(providerId)) {
        providerMap.set(providerId, {
          name: model.provider_name ?? "Unknown Provider",
          type: model.provider_type ?? null,
          models: []
        });
      }
      providerMap.get(providerId)!.models.push(model);
    }
  }

  const groups: ModelGroup[] = [];

  // Add system models group first if there are any
  if (systemModels.length > 0) {
    systemModels.sort((a, b) => (a.nickname ?? "").localeCompare(b.nickname ?? ""));
    groups.push({
      id: null,
      label: systemModelsLabel,
      providerType: null,
      models: systemModels
    });
  }

  // Sort provider groups alphabetically and add them
  const sortedProviders = Array.from(providerMap.entries()).sort(([, a], [, b]) =>
    a.name.localeCompare(b.name)
  );

  for (const [providerId, provider] of sortedProviders) {
    provider.models.sort((a, b) => (a.nickname ?? "").localeCompare(b.nickname ?? ""));
    groups.push({
      id: providerId,
      label: provider.name,
      providerType: provider.type,
      models: provider.models
    });
  }

  return groups;
}
