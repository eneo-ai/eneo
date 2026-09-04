/**
 * Built-in image generation provider: the admin picks a tenant model provider
 * and a model; Eneo calls it through its own loopback MCP server. These are
 * the option lists the dialog renders and the suggestions it offers per
 * provider type. The backend validates sizes and qualities against the same
 * lists.
 */

export const BUILTIN_IMAGE_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"] as const;
export const BUILTIN_IMAGE_QUALITIES = ["auto", "low", "medium", "high"] as const;

/** Purposes that offer a built-in provider. Mirrors the backend constant. */
export const BUILTIN_PROVIDER_PURPOSES: readonly string[] = ["image_generation"];

const MODEL_SUGGESTIONS: Record<string, readonly string[]> = {
  openai: ["gpt-image-1", "gpt-image-1-mini", "dall-e-3"],
  gemini: ["imagen-4.0-generate-001", "imagen-4.0-fast-generate-001"],
  vertex_ai: ["imagen-4.0-generate-001"],
  bedrock: ["amazon.nova-canvas-v1:0"]
};

/**
 * Model names worth offering for a provider type. Azure deployments are
 * named by the tenant, so nothing is suggested there; unknown types get an
 * empty list and the admin types the name.
 */
export function suggestedImageModels(providerType: string | null | undefined): readonly string[] {
  if (!providerType) return [];
  return MODEL_SUGGESTIONS[providerType.toLowerCase()] ?? [];
}

export function hasBuiltinProvider(purpose: string | null | undefined): boolean {
  return !!purpose && BUILTIN_PROVIDER_PURPOSES.includes(purpose);
}
