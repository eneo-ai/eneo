type Model = { id: string };

type EffectiveModelConfig<T extends Model> = {
  models_enforced: boolean;
  default_model?: T | null;
  locked_model?: T | null;
  available_models: T[];
};

export function selectEffectiveChatModel<T extends Model>(
  current: T | null | undefined,
  config: EffectiveModelConfig<T> | null | undefined,
  catalog: T[] = []
): T | undefined {
  if (!config?.models_enforced) return current ?? undefined;

  const allowedIds = new Set(config.available_models.map((model) => model.id));
  if (current && allowedIds.has(current.id)) return current;

  const fallback =
    config.default_model ?? config.locked_model ?? config.available_models[0] ?? undefined;
  if (!fallback) return undefined;
  return catalog.find((model) => model.id === fallback.id) ?? fallback;
}
