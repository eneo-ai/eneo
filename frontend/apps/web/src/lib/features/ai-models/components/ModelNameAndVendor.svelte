<script context="module" lang="ts">
  // Available chart colors for organizations
  const chartColors = [
    "chart-green",
    "chart-moss",
    "chart-red",
    "chart-intric",
    "chart-yellow",
    "chart-blue",
    "accent-default"
  ];

  // Simple hash function to get a consistent index from a string
  function hashString(str: string): number {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash = hash & hash; // Convert to 32bit integer
    }
    return Math.abs(hash);
  }

  // Get a consistent chart color for any identifier (provider name, org, etc.)
  export function getChartColour(identifier: string | undefined | null): string {
    if (!identifier) return chartColors[0];
    const index = hashString(identifier) % chartColors.length;
    return chartColors[index];
  }
</script>

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let model:
    | CompletionModel
    | EmbeddingModel
    | TranscriptionModel
    | { org: string; nickname: string; name: string; description: string };
  export let size: "card" | "table" = "table";
  export let showTokenLimit: boolean = true;

  // Format token limit for display (e.g., 128000 -> "128K")
  function formatTokenLimit(limit: number): string {
    if (limit >= 1_000_000) return `${(limit / 1_000_000).toFixed(limit % 1_000_000 === 0 ? 0 : 1)}M`;
    if (limit >= 1_000) return `${Math.round(limit / 1_000)}K`;
    return limit.toString();
  }
</script>

{#if size === "card"}
  <div class="flex items-center justify-start gap-4">
    <h4 class="text-primary text-2xl leading-6 font-extrabold">
      {"nickname" in model ? model.nickname : model.name}
    </h4>
  </div>
{:else}
  <div class="flex flex-col gap-0.5">
    <Tooltip text={model.description ?? model.name}>
      <h4 class="text-primary leading-tight">
        {"nickname" in model ? model.nickname : model.name}
      </h4>
    </Tooltip>
    {#if "nickname" in model && model.name !== model.nickname}
      <span class="text-xs text-muted leading-tight truncate max-w-48" title={model.name}>
        {model.name}
      </span>
    {/if}
    {#if showTokenLimit && "token_limit" in model && model.token_limit}
      <span class="text-[11px] text-muted/70 tabular-nums leading-none">
        {m.token_limit_context({ limit: formatTokenLimit(model.token_limit) })}
      </span>
    {/if}
  </div>
{/if}
