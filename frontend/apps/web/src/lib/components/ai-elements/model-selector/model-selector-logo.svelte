<script lang="ts" module>
  // Logos are auto-discovered from `$lib/assets/provider-logos/*` (same source as
  // the admin ProviderGlyph). `provider` accepts either a model vendor/org
  // ("OpenAI", "Anthropic", "Google") or a hosting provider_type ("azure",
  // "bedrock_converse") — aliases map vendors without a logo of their own onto
  // the closest asset.
  const logoModules = import.meta.glob("$lib/assets/provider-logos/*.{svg,png,jpg,jpeg,webp}", {
    eager: true,
    query: "?url",
    import: "default"
  });

  const logos: Record<string, string> = {};
  for (const [path, url] of Object.entries(logoModules)) {
    const filename = path.split("/").pop() ?? "";
    const name = filename.replace(/\.\w+$/, "");
    if (!logos[name]) logos[name] = url as string; // SVG takes priority (sorted first)
  }

  const aliases: Record<string, string> = {
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
    key = aliases[key] ?? key;
    return logos[key];
  }
</script>

<script lang="ts">
  import { cn } from "$lib/utils.js";

  type Props = { provider: string | null | undefined; class?: string };

  let { provider, class: className }: Props = $props();

  const logoUrl = $derived(resolveLogo(provider));
</script>

{#if logoUrl}
  <img
    data-slot="model-selector-logo"
    src={logoUrl}
    alt=""
    aria-hidden="true"
    class={cn("size-4 shrink-0 object-contain", className)}
  />
{:else}
  <svg
    data-slot="model-selector-logo"
    class={cn("text-muted-foreground size-4 shrink-0", className)}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <rect x="4" y="4" width="6" height="6" rx="1" />
    <rect x="14" y="4" width="6" height="6" rx="1" />
    <rect x="4" y="14" width="6" height="6" rx="1" />
    <rect x="14" y="14" width="6" height="6" rx="1" />
  </svg>
{/if}
