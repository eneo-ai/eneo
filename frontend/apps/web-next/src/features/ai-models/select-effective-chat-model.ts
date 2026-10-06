type ModelRef = { id: string };

export type EffectiveModelConfig = {
  models_enforced: boolean;
  default_model?: ModelRef | null;
  locked_model?: ModelRef | null;
  available_models: ModelRef[];
};

/**
 * Resolve which completion model the chat actually runs, honouring the admin
 * governance policy. When models are enforced, the current pick must be in the
 * allow-list; otherwise we fall back to the policy default / locked / first
 * allowed model. Returns the model id (callers re-look up the full record from
 * the live catalog). Ported from the Svelte `selectEffectiveChatModel`.
 */
export function selectEffectiveModelId(
  currentId: string | null | undefined,
  config: EffectiveModelConfig | null | undefined
): string | undefined {
  if (!config?.models_enforced) return currentId ?? undefined;

  const allowedIds = new Set(config.available_models.map((model) => model.id));
  if (currentId && allowedIds.has(currentId)) return currentId;

  return (
    config.default_model?.id ??
    config.locked_model?.id ??
    config.available_models[0]?.id ??
    undefined
  );
}
