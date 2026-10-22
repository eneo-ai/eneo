import { m } from "$lib/paraglide/messages";
import { prettifyProviderType } from "./groupModels";

// Structural so that legacy shapes (and fixtures with only `{ id, name }`)
// satisfy it; every field beyond `name` is optional.
export type ModelLabelFields = {
  name: string;
  nickname?: string | null;
  provider_name?: string | null;
  provider_type?: string | null;
};

export type EmbeddingModelStatusFields = {
  is_org_enabled?: boolean | null;
};

/** Human-facing name: the admin-set nickname, else the underlying model id. */
export function modelDisplayName(model: ModelLabelFields): string {
  return model.nickname?.trim() || model.name;
}

/** Hosting provider label: the tenant's provider name, else a prettified provider type. */
export function modelProviderLabel(model: ModelLabelFields): string | null {
  return model.provider_name?.trim() || prettifyProviderType(model.provider_type) || null;
}

/**
 * Label for an embedding model wherever it stands alone (knowledge group
 * headers, model pickers). The provider is always appended when known so two
 * models with the same name from different providers never collide.
 */
export function embeddingModelLabel(model: ModelLabelFields): string {
  const provider = modelProviderLabel(model);
  const name = modelDisplayName(model);
  return provider ? `${name} (${provider})` : name;
}

/**
 * Why knowledge under this model cannot receive new content, or `null` when it
 * can. Distinguishes an org-wide disable (an administrator must re-enable it)
 * from a model that simply is not selected for the space.
 */
export function embeddingModelStatusLabel(
  model: EmbeddingModelStatusFields,
  inSpace: boolean
): string | null {
  if (inSpace) return null;
  if (model.is_org_enabled === false) return m.embedding_model_disabled_by_admin();
  if (model.is_org_enabled === true) return m.embedding_model_not_in_space();
  return m.disabled();
}

/** Group header for a knowledge table: the model label plus its status, if any. */
export function embeddingModelGroupTitle(
  model: ModelLabelFields & EmbeddingModelStatusFields,
  inSpace: boolean
): string {
  const status = embeddingModelStatusLabel(model, inSpace);
  const label = embeddingModelLabel(model);
  return status ? `${label} (${status})` : label;
}
