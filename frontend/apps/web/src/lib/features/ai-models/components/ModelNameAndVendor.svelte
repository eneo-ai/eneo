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

  export let model:
    | CompletionModel
    | EmbeddingModel
    | TranscriptionModel
    | { org: string; nickname: string; name: string; description: string };
  export let size: "card" | "table" = "table";
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
  </div>
{/if}
