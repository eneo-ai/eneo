<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  /**
   * ProviderGlyph - Abstract geometric symbols for AI providers
   * Uses subtle tinted backgrounds to avoid harsh color blocks
   */

  export let providerType: "openai" | "azure" | "anthropic" | "gemini" | "cohere" | string;
  export let size: "sm" | "md" | "lg" = "md";

  // Size mappings
  const sizes = {
    sm: { chip: "w-6 h-6", icon: "w-3 h-3", radius: "rounded-md" },
    md: { chip: "w-8 h-8", icon: "w-4 h-4", radius: "rounded-lg" },
    lg: { chip: "w-10 h-10", icon: "w-5 h-5", radius: "rounded-lg" }
  };

  $: sizeConfig = sizes[size];

  // Provider color configurations - WCAG 2.1 AA compliant (3:1 for UI components)
  // Light mode: fg 35-42% L on 93-94% L bg (ensures 3:1+ contrast)
  // Dark mode: fg 80-82% L on 20-23% L bg (ensures 3:1+ contrast)
  const providerColors: Record<string, { bg: string; fg: string; border: string }> = {
    openai: {
      bg: "bg-[oklch(94%_0.035_165)] dark:bg-[oklch(22%_0.06_165)]",
      fg: "text-[oklch(35%_0.14_165)] dark:text-[oklch(80%_0.14_165)]",
      border: "border-[oklch(85%_0.05_165)] dark:border-[oklch(35%_0.08_165)]"
    },
    azure: {
      bg: "bg-[oklch(93%_0.04_250)] dark:bg-[oklch(20%_0.07_250)]",
      fg: "text-[oklch(38%_0.16_250)] dark:text-[oklch(82%_0.16_250)]",
      border: "border-[oklch(82%_0.06_250)] dark:border-[oklch(34%_0.09_250)]"
    },
    anthropic: {
      bg: "bg-[oklch(94%_0.045_35)] dark:bg-[oklch(23%_0.06_35)]",
      fg: "text-[oklch(42%_0.16_35)] dark:text-[oklch(82%_0.14_35)]",
      border: "border-[oklch(84%_0.06_35)] dark:border-[oklch(36%_0.07_35)]"
    },
    gemini: {
      bg: "bg-[oklch(93%_0.035_260)] dark:bg-[oklch(20%_0.06_260)]",
      fg: "text-[oklch(38%_0.16_260)] dark:text-[oklch(82%_0.15_260)]",
      border: "border-[oklch(83%_0.05_260)] dark:border-[oklch(34%_0.08_260)]"
    },
    cohere: {
      bg: "bg-[oklch(93%_0.04_290)] dark:bg-[oklch(21%_0.07_290)]",
      fg: "text-[oklch(38%_0.17_290)] dark:text-[oklch(82%_0.16_290)]",
      border: "border-[oklch(83%_0.06_290)] dark:border-[oklch(35%_0.09_290)]"
    },
    mistral: {
      bg: "bg-[oklch(94%_0.04_55)] dark:bg-[oklch(22%_0.06_55)]",
      fg: "text-[oklch(40%_0.15_55)] dark:text-[oklch(81%_0.14_55)]",
      border: "border-[oklch(84%_0.05_55)] dark:border-[oklch(35%_0.07_55)]"
    },
    hosted_vllm: {
      bg: "bg-[oklch(93%_0.035_140)] dark:bg-[oklch(21%_0.06_140)]",
      fg: "text-[oklch(37%_0.14_140)] dark:text-[oklch(80%_0.13_140)]",
      border: "border-[oklch(83%_0.05_140)] dark:border-[oklch(34%_0.07_140)]"
    }
  };

  // Default fallback for unknown providers
  const defaultColors = {
    bg: "bg-surface-dimmer",
    fg: "text-muted",
    border: "border-dimmer"
  };

  $: colors = providerColors[providerType] || defaultColors;
</script>

<div
  class="
    {sizeConfig.chip}
    {sizeConfig.radius}
    {colors.bg}
    {colors.border}
    border
    flex items-center justify-center
    shadow-[inset_0_1px_2px_oklch(0%_0_0/0.05)]
    transition-all duration-150 ease-out
    hover:translate-y-[-1px]
    hover:shadow-sm
  "
  title={providerType}
>
  <svg
    class="{sizeConfig.icon} {colors.fg}"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    {#if providerType === "openai"}
      <!-- Overlapping circles - neural connections -->
      <circle cx="9" cy="12" r="5" />
      <circle cx="15" cy="12" r="5" />
    {:else if providerType === "azure"}
      <!-- Angled parallelogram stack - cloud layers -->
      <path d="M4 8 L12 4 L20 8 L12 12 Z" />
      <path d="M4 12 L12 8 L20 12 L12 16 Z" />
      <path d="M4 16 L12 12 L20 16 L12 20 Z" />
    {:else if providerType === "anthropic"}
      <!-- Rounded hexagon - organic meets technical -->
      <path d="M12 2 L20 7 L20 17 L12 22 L4 17 L4 7 Z" stroke-linejoin="round" />
    {:else if providerType === "gemini"}
      <!-- Twin stars/dots - duality -->
      <circle cx="8" cy="12" r="3" fill="currentColor" />
      <circle cx="16" cy="12" r="3" fill="currentColor" />
    {:else if providerType === "cohere"}
      <!-- Flowing wave/ribbon - coherence -->
      <path d="M2 12 Q7 6, 12 12 T22 12" />
      <path d="M2 16 Q7 10, 12 16 T22 16" />
    {:else if providerType === "mistral"}
      <!-- Diagonal stripes - wind/mistral -->
      <line x1="4" y1="4" x2="12" y2="20" />
      <line x1="10" y1="4" x2="18" y2="20" />
      <line x1="16" y1="4" x2="24" y2="20" />
    {:else if providerType === "hosted_vllm"}
      <!-- Chevron/V shape - vLLM -->
      <polyline points="4,6 12,18 20,6" />
    {:else}
      <!-- Default: simple square grid for unknown providers -->
      <rect x="4" y="4" width="6" height="6" rx="1" />
      <rect x="14" y="4" width="6" height="6" rx="1" />
      <rect x="4" y="14" width="6" height="6" rx="1" />
      <rect x="14" y="14" width="6" height="6" rx="1" />
    {/if}
  </svg>
</div>
