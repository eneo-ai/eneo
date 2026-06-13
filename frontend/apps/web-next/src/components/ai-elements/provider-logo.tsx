import { cn } from "@/lib/utils";

/**
 * Provider/vendor logos served from `public/provider-logos/*` (ported 1:1 from
 * the Svelte app's `assets/provider-logos`). `provider` accepts either a model
 * vendor/org ("OpenAI", "Anthropic", "Google") or a hosting `provider_type`
 * ("azure", "bedrock_converse"); aliases map vendors without their own asset
 * onto the closest logo. Falls back to a neutral grid glyph.
 */
const LOGO_FILES: Record<string, string> = {
  ai21: "ai21.svg",
  aiml_api: "aiml_api.svg",
  anthropic: "anthropic.svg",
  assemblyai: "assemblyai.png",
  aws: "aws.svg",
  azure: "azure.svg",
  azure_ai_foundry: "azure_ai_foundry.png",
  baseten: "baseten.svg",
  bedrock: "bedrock.svg",
  cerebras: "cerebras.svg",
  cloudflare: "cloudflare.svg",
  cohere: "cohere.svg",
  databricks: "databricks.svg",
  dataforseo: "dataforseo.png",
  deepgram: "deepgram.png",
  deepinfra: "deepinfra.png",
  deepseek: "deepseek.svg",
  elevenlabs: "elevenlabs.png",
  exa_ai: "exa_ai.png",
  fal_ai: "fal_ai.jpg",
  featherless: "featherless.svg",
  fireworks_ai: "fireworks_ai.svg",
  friendli: "friendli.svg",
  gemini: "gemini.svg",
  google_pse: "google_pse.png",
  groq: "groq.svg",
  hosted_vllm: "hosted_vllm.svg",
  huggingface: "huggingface.svg",
  hyperbolic: "hyperbolic.svg",
  infinity: "infinity.png",
  javelin: "javelin.png",
  jina: "jina.png",
  lambda: "lambda.svg",
  meta_llama: "meta_llama.svg",
  minimax: "minimax.svg",
  mistral: "mistral.svg",
  moonshot: "moonshot.svg",
  morph: "morph.svg",
  nebius: "nebius.svg",
  novita: "novita.svg",
  nvidia_nim: "nvidia_nim.svg",
  nvidia_triton: "nvidia_triton.png",
  ollama: "ollama.svg",
  openai: "openai.svg",
  openrouter: "openrouter.svg",
  oracle: "oracle.svg",
  perplexity: "perplexity.svg",
  qwen: "qwen.png",
  recraft: "recraft.svg",
  replicate: "replicate.svg",
  runway: "runway.png",
  sambanova: "sambanova.svg",
  sap: "sap.png",
  search1api: "search1api.png",
  snowflake: "snowflake.svg",
  tavily: "tavily.png",
  together_ai: "together_ai.svg",
  vertex_ai: "vertex_ai.svg",
  vllm: "vllm.png",
  volcengine: "volcengine.png",
  voyage: "voyage.webp",
  watsonx: "watsonx.svg",
  xai: "xai.svg",
  xinference: "xinference.svg",
  zscaler: "zscaler.svg"
};

const ALIASES: Record<string, string> = {
  google: "gemini",
  meta: "meta_llama",
  microsoft: "azure",
  amazon: "bedrock",
  bedrock_converse: "bedrock"
};

function resolveLogo(provider: string | null | undefined): string | undefined {
  if (!provider) return undefined;
  let key = provider.toLowerCase().trim().replace(/\s+/g, "_");
  if (key.startsWith("vertex_ai")) key = "vertex_ai";
  key = ALIASES[key] ?? key;
  const file = LOGO_FILES[key];
  return file ? `/provider-logos/${file}` : undefined;
}

export function ProviderLogo({
  provider,
  className
}: {
  provider: string | null | undefined;
  className?: string;
}) {
  const url = resolveLogo(provider);

  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- static SVG/PNG asset; next/image blocks SVG without dangerouslyAllowSVG
      <img
        src={url}
        alt=""
        aria-hidden="true"
        className={cn("size-4 shrink-0 object-contain", className)}
      />
    );
  }

  return (
    <svg
      className={cn("text-muted-foreground size-4 shrink-0", className)}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="4" y="4" width="6" height="6" rx="1" />
      <rect x="14" y="4" width="6" height="6" rx="1" />
      <rect x="4" y="14" width="6" height="6" rx="1" />
      <rect x="14" y="14" width="6" height="6" rx="1" />
    </svg>
  );
}
