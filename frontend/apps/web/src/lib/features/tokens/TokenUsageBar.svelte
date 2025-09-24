<script lang="ts">
  import { Tooltip, Button } from "@intric/ui";
  import { AlertTriangle } from "lucide-svelte";

  interface Props {
    tokens: number;
    limit: number;
    isApproximate?: boolean;
  }

  const { tokens = 0, limit = 128000, isApproximate = false }: Props = $props();

  // Calculate actual percentage (can exceed 100%)
  const actualPercentage = $derived(limit > 0 ? (tokens / limit) * 100 : 0);

  // Calculate display percentage for progress bar (capped at 100% for normal section)
  const displayPercentage = $derived(Math.min(actualPercentage, 100));

  // Check if we're in overflow state
  const isOverflow = $derived(actualPercentage > 100);

  // Calculate overflow tokens
  const overflowTokens = $derived(Math.max(0, tokens - limit));

  // Determine color based on percentage using design tokens
  const colorClass = $derived(
    isOverflow
      ? 'bg-negative-default'
      : displayPercentage < 70
        ? 'bg-positive-default'
        : displayPercentage < 85
          ? 'bg-warning-default'
          : displayPercentage < 95
            ? 'bg-change-indicator'
            : 'bg-negative-default'
  );

  // Format numbers with locale-aware thousands separators
  const formattedTokens = $derived(tokens.toLocaleString());
  const formattedLimit = $derived(limit.toLocaleString());
  const formattedOverflow = $derived(overflowTokens.toLocaleString());
</script>

<div class="token-usage-bar w-full">
  <!-- Progress bar -->
  <div class="relative mb-1 h-1.5 w-full overflow-hidden rounded-full bg-tertiary">
    <!-- Normal usage section (up to 100%) -->
    <div
      class="absolute left-0 top-0 h-full rounded-full transition-all duration-300 ease-out {colorClass}"
      style="width: {displayPercentage}%"
    ></div>

    <!-- Overflow section (beyond 100%) -->
    {#if isOverflow}
      <div
        class="absolute left-0 top-0 h-full rounded-full bg-negative-stronger opacity-80 transition-all duration-300 ease-out"
        style="width: {Math.min(actualPercentage, 120)}%"
      ></div>
    {/if}
  </div>

  <!-- Text display -->
  <div class="flex items-center justify-between text-xs text-secondary">
    <div class="flex items-center gap-1">
      {#if isApproximate && !isOverflow}
        <span class="text-tertiary">≈</span>
      {/if}
      <span>{formattedTokens} / {formattedLimit} tokens</span>
    </div>

    <div class="flex items-center gap-3">
      {#if isOverflow}
        <Tooltip text="You've exceeded the context limit. The AI may not see the oldest messages or file content." placement="top" let:trigger asFragment>
          <Button
            unstyled
            is={trigger}
            class="flex cursor-help items-center gap-1 rounded-md p-1 transition-colors duration-200 hover:bg-negative-dimmer/60 -m-1"
          >
            <AlertTriangle class="h-4 w-4 flex-shrink-0 text-negative-stronger" />
            <span class="font-medium text-negative-stronger">({formattedOverflow} over)</span>
          </Button>
        </Tooltip>
      {/if}

      <span
        class="{isOverflow
          ? 'font-bold text-negative-stronger'
          : displayPercentage > 85
            ? 'font-medium text-warning'
            : ''}">{actualPercentage.toFixed(1)}%</span
      >
    </div>
  </div>
</div>

<style>
  .token-usage-bar {
    /* Ensures smooth animations */
    will-change: width;
  }
</style>