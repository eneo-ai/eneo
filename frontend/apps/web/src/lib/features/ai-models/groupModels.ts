// Only the fields the vendor grouping actually reads — `org` is the model
// vendor (OpenAI, Anthropic…), distinct from the hosting provider. Kept minimal
// (no index signature) so CompletionModel/TranscriptionModel satisfy it directly.
type VendorFields = {
  org?: string | null;
  provider_name?: string | null;
  provider_type?: string | null;
};

export type VendorGroup<T> = {
  label: string;
  models: T[];
};

/** "azure_openai" → "Azure Openai". Used as a last-resort group label. */
export function prettifyProviderType(type: string | null | undefined): string | null {
  if (!type) return null;
  return type
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Groups models by vendor (`org`), falling back to the provider name, then a
 * prettified provider type, then `otherLabel`. Groups are sorted alphabetically;
 * model order within a group is preserved (sort the input beforehand). Shared by
 * the chat and settings model selectors so they group identically.
 */
export function groupModelsByVendor<T extends VendorFields>(
  models: T[],
  otherLabel: string
): VendorGroup<T>[] {
  const groups = new Map<string, VendorGroup<T>>();
  for (const model of models) {
    const label =
      model.org?.trim() ||
      model.provider_name?.trim() ||
      prettifyProviderType(model.provider_type) ||
      otherLabel;
    let group = groups.get(label);
    if (!group) {
      group = { label, models: [] };
      groups.set(label, group);
    }
    group.models.push(model);
  }
  return Array.from(groups.values()).sort((a, b) => a.label.localeCompare(b.label));
}
