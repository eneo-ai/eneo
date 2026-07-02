const PROVIDER_LOGO_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  // Display-only aliases. These never change provider identity, credentials,
  // model routing, persisted provider_type values, or LiteLLM model names.
  amazon: "bedrock",
  amazon_nova: "aws",
  azure_ai: "azure",
  azure_text: "azure",
  bedrock_converse: "bedrock",
  bedrock_mantle: "bedrock",
  codestral: "mistral",
  cohere_chat: "cohere",
  featherless_ai: "featherless",
  fireworks: "fireworks_ai",
  "fireworks_ai-embedding-models": "fireworks_ai",
  friendliai: "friendli",
  google: "gemini",
  lambda_ai: "lambda",
  meta: "meta_llama",
  microsoft: "azure",
  oci: "oracle",
  palm: "gemini",
  sagemaker: "aws",
  "text-completion-codestral": "mistral",
  "text-completion-openai": "openai",
  zai: "qwen"
});

export function resolveProviderLogoType(provider: string | null | undefined): string | undefined {
  if (!provider) return undefined;

  const key = provider.toLowerCase().trim().replace(/\s+/g, "_");
  if (!key) return undefined;

  if (key.startsWith("vertex_ai")) return "vertex_ai";

  return PROVIDER_LOGO_ALIASES[key] ?? key;
}
