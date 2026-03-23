<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  /**
   * ProviderGlyph - Provider logos with chip styling
   * Logos are auto-discovered from provider-logos/* via Vite glob import.
   * To add a new provider: drop a {provider_type}.{svg,png,jpg,webp} in the folder. No code change needed.
   */

  // Accept both prop names (some callers use `type`, some use `providerType`)
  export let providerType: string = "";
  export let type: string = "";
  export let size: "sm" | "md" | "lg" = "md";

  const sizes = {
    sm: { chip: "w-6 h-6", img: "w-3.5 h-3.5", icon: "w-3 h-3", radius: "rounded-md" },
    md: { chip: "w-8 h-8", img: "w-5 h-5", icon: "w-4 h-4", radius: "rounded-lg" },
    lg: { chip: "w-10 h-10", img: "w-6 h-6", icon: "w-5 h-5", radius: "rounded-lg" }
  };

  // Glob import all image assets at build time — no hardcoded mapping needed
  const logoModules = import.meta.glob(
    "$lib/assets/provider-logos/*.{svg,png,jpg,jpeg,webp}",
    { eager: true, query: "?url", import: "default" }
  );

  const logos: Record<string, string> = {};
  for (const [path, url] of Object.entries(logoModules)) {
    const filename = path.split("/").pop() ?? "";
    const name = filename.replace(/\.\w+$/, "");
    if (!logos[name]) logos[name] = url as string; // SVG takes priority (sorted first)
  }

  function normalize(t: string): string {
    if (t === "bedrock_converse") return "bedrock";
    if (t.startsWith("vertex_ai")) return "vertex_ai";
    return t;
  }

  $: resolvedType = normalize(providerType || type);
  $: logoUrl = logos[resolvedType];
  $: sizeConfig = sizes[size];
</script>

<div
  class="
    {sizeConfig.chip}
    {sizeConfig.radius}
    bg-surface-dimmer dark:bg-surface-dimmest
    border border-dimmer
    flex items-center justify-center
    shadow-[inset_0_1px_2px_oklch(0%_0_0/0.05)]
    transition-all duration-150 ease-out
    hover:translate-y-[-1px]
    hover:shadow-sm
  "
  title={resolvedType}
>
  {#if logoUrl}
    <img
      src={logoUrl}
      alt={resolvedType}
      class="{sizeConfig.img} object-contain dark:brightness-90 dark:contrast-125"
      class:dark-invert={resolvedType === "openai" || resolvedType === "anthropic" || resolvedType === "ollama" || resolvedType === "replicate"}
    />
  {:else}
    <!-- Fallback: generic grid icon for unknown providers -->
    <svg
      class="{sizeConfig.icon} text-muted"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <rect x="4" y="4" width="6" height="6" rx="1" />
      <rect x="14" y="4" width="6" height="6" rx="1" />
      <rect x="4" y="14" width="6" height="6" rx="1" />
      <rect x="14" y="14" width="6" height="6" rx="1" />
    </svg>
  {/if}
</div>

<style>
  :global(.dark) .dark-invert {
    filter: invert(1) hue-rotate(180deg);
  }
</style>
