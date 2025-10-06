<script lang="ts">
  import { Tooltip, Button } from "@intric/ui";
  import { AlertTriangle } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    tokens: number; // Tokens for the NEW prompt (text + files)
    limit: number;
    historyTokens?: number; // Tokens for the conversation HISTORY
    isApproximate?: boolean;
  }

  const { tokens = 0, limit = 128000, historyTokens = 0, isApproximate = false }: Props = $props();

  // --- Calculations ---
  // Use tokens directly in calculations for proper reactivity
  const grandTotalTokens = $derived(historyTokens + tokens);

  const historyPercentage = $derived(limit > 0 ? (historyTokens / limit) * 100 : 0);
  const newPercentage = $derived(limit > 0 ? (tokens / limit) * 100 : 0);
  const totalPercentage = $derived(historyPercentage + newPercentage);

  // Display percentages (capped at 100% for bar visualization)
  const historyDisplayPercentage = $derived(Math.min(historyPercentage, 100));
  // Don't cap the new segment - let it show its full percentage even if it overflows
  const newDisplayPercentage = $derived(newPercentage);

  const isOverflow = $derived(totalPercentage > 100);
  const overflowTokens = $derived(Math.max(0, grandTotalTokens - limit));

  // Color logic for the NEW prompt segment based on total usage
  const newSegmentColorClass = $derived(
    isOverflow
      ? 'bg-negative-default'
      : totalPercentage < 70
        ? 'bg-positive-default'
        : totalPercentage < 85
          ? 'bg-warning-default'
        : totalPercentage < 95
            ? 'bg-[var(--change-indicator)]'
            : 'bg-negative-default'
  );

  // History segment always has a neutral color
  const historySegmentColorClass = 'bg-slate-400';

  // --- Formatting ---
  const formattedGrandTotal = $derived(grandTotalTokens.toLocaleString());
  const formattedHistoryTokens = $derived(historyTokens.toLocaleString());
  const formattedNewTokens = $derived(tokens.toLocaleString());
  const formattedLimit = $derived(limit.toLocaleString());
  const formattedOverflow = $derived(overflowTokens.toLocaleString());
</script>

<div class="token-usage-bar w-full">
  <!-- Stacked progress bar -->
  <div class="relative mb-1 h-1.5 w-full overflow-hidden rounded-full bg-tertiary">
    <!-- History segment (left) -->
    {#if historyTokens > 0}
      <Tooltip
        text={m.tokens_from_conversation_history({ tokens: formattedHistoryTokens })}
        placement="top"
        let:trigger
        asFragment
      >
        <Button
          unstyled
          is={trigger}
          class="absolute left-0 top-0 h-full cursor-help transition-all duration-300 ease-out {historySegmentColorClass}"
          style="width: {historyDisplayPercentage}%"
        />
      </Tooltip>
    {/if}

    <!-- New prompt segment (right) -->
    {#if tokens > 0}
      <Tooltip
        text={m.tokens_from_new_message({ tokens: formattedNewTokens })}
        placement="top"
        let:trigger
        asFragment
      >
        <Button
          unstyled
          is={trigger}
          class="absolute top-0 h-full cursor-help transition-all duration-300 ease-out {newSegmentColorClass}"
          style="left: {historyDisplayPercentage}%; width: {newDisplayPercentage}%"
        >
          <!-- Vertical separator line between segments -->
          {#if historyTokens > 0 && historyDisplayPercentage < 100}
            <div class="absolute left-0 top-0 h-full w-px bg-primary/30"></div>
          {/if}
        </Button>
      </Tooltip>
    {/if}

    <!-- Overflow section (beyond 100%) -->
    {#if isOverflow}
      <div
        class="absolute left-0 top-0 h-full rounded-full bg-negative-stronger opacity-80 transition-all duration-300 ease-out"
        style="width: {Math.min(totalPercentage, 120)}%"
      ></div>
    {/if}
  </div>

  <!-- Text display -->
  <div class="flex items-center justify-between text-xs text-secondary">
    <div class="flex items-center gap-1.5">
      {#if isApproximate && !isOverflow}
        <span class="text-tertiary">≈</span>
      {/if}
      <span>{formattedGrandTotal} / {formattedLimit} {m.tokens().toLowerCase()}</span>

      <!-- Legend indicators for segments -->
      {#if historyTokens > 0 || tokens > 0}
        <div class="flex items-center gap-2 ml-2">
          {#if historyTokens > 0}
            <div class="flex items-center gap-1">
              <div class="w-2 h-2 rounded-full {historySegmentColorClass}"></div>
              <span class="text-[10px] text-tertiary">{m.history_label()}</span>
            </div>
          {/if}
          {#if tokens > 0}
            <div class="flex items-center gap-1">
              <div class="w-2 h-2 rounded-full {newSegmentColorClass}"></div>
              <span class="text-[10px] text-tertiary">{m.new_label()}</span>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <div class="flex items-center gap-3">
      {#if isOverflow}
        <Tooltip
          text={m.context_limit_exceeded()}
          placement="top"
          let:trigger
          asFragment
        >
          <Button
            unstyled
            is={trigger}
            class="flex cursor-help items-center gap-1 rounded-md p-1 transition-colors duration-200 hover:bg-negative-dimmer/60 -m-1"
          >
            <AlertTriangle class="h-4 w-4 flex-shrink-0 text-negative-stronger" />
            <span class="font-medium text-negative-stronger">({formattedOverflow} {m.over()})</span>
          </Button>
        </Tooltip>
      {/if}

      <span
        class="{isOverflow
          ? 'font-bold text-negative-stronger'
          : totalPercentage > 85
            ? 'font-medium text-warning'
            : ''}">{totalPercentage.toFixed(1)}%</span
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
