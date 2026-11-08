import { modelDisplayName } from "@/lib/models/model-display-name";
import type { EmbeddingModel } from "./knowledge";

/** Hosting provider distinguishes otherwise identical embedding model names. */
export function embeddingModelLabel(model: EmbeddingModel): string {
  const provider =
    model.provider_name?.trim() ||
    model.provider_type
      ?.split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  const name = modelDisplayName(model);
  return provider ? `${name} (${provider})` : name;
}

export function embeddingModelGroupTitle(
  model: EmbeddingModel,
  inSpace: boolean,
  t: (key: string) => string
): string {
  const label = embeddingModelLabel(model);
  if (inSpace) return label;
  const status =
    model.is_org_enabled === false
      ? "embedding_model_disabled_by_admin"
      : model.is_org_enabled === true
        ? "embedding_model_not_in_space"
        : "disabled";
  return `${label} (${t(status)})`;
}
