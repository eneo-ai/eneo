<script lang="ts">
  import { Tooltip, Button } from "@intric/ui";
  import { AlertTriangle } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    tokens: number; // Tokens for the NEW prompt (text + files)
    limit: number;
    historyTokens?: number; // Tokens for the conversation HISTORY (excludes assistant prompt)
    promptTokens?: number; // Assistant prompt tokens counted once
    isApproximate?: boolean;
  }

  const {
    tokens = 0,
    limit = 128000,
    historyTokens = 0,
    promptTokens = 0,
    isApproximate = false
  }: Props = $props();

  // --- Calculations ---
  // Combine prompt tokens with history so the assistant prompt is only counted once
  const combinedHistoryTokens = $derived(historyTokens + promptTokens);
  const grandTotalTokens = $derived(combinedHistoryTokens + tokens);

  const historyPercentage = $derived(limit > 0 ? (combinedHistoryTokens / limit) * 100 : 0);
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
      ? "bg-negative-stronger"
      : totalPercentage < 70
        ? "bg-positive-stronger"
        : totalPercentage < 85
          ? "bg-warning-stronger"
          : totalPercentage < 95
            ? "bg-warning-stronger"
            : "bg-negative-stronger"
  );

  // History segment always has a neutral color
  const historySegmentColorClass = "bg-slate-400";

  // --- Formatting ---
  const formattedGrandTotal = $derived(grandTotalTokens.toLocaleString());
  const formattedHistoryTokens = $derived(combinedHistoryTokens.toLocaleString());
  const formattedNewTokens = $derived(tokens.toLocaleString());
  const formattedLimit = $derived(limit.toLocaleString());
  const formattedOverflow = $derived(overflowTokens.toLocaleString());
</script>

<div class="token-usage-bar w-full">
  <!-- Stacked progress bar -->
  <div class="bg-tertiary relative mb-1 h-1.5 w-full overflow-hidden rounded-full">
    <!-- History segment (left) -->
    {#if combinedHistoryTokens > 0}
      <Tooltip
        text={m.tokens_from_conversation_history({ tokens: formattedHistoryTokens })}
        placement="top"
        let:trigger
        asFragment
      >
        <Button
          unstyled
          is={trigger}
          class="absolute top-0 left-0 h-full cursor-help transition-all duration-300 ease-out {historySegmentColorClass}"
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
          {#if combinedHistoryTokens > 0 && historyDisplayPercentage < 100}
            <div class="bg-primary/30 absolute top-0 left-0 h-full w-px"></div>
          {/if}
        </Button>
      </Tooltip>
    {/if}

    <!-- Overflow section (beyond 100%) -->
    {#if isOverflow}
      <div
        class="bg-negative-stronger absolute top-0 left-0 h-full rounded-full opacity-80 transition-all duration-300 ease-out"
        style="width: {Math.min(totalPercentage, 120)}%"
      ></div>
    {/if}
  </div>

  <!-- Text display -->
  <div class="text-secondary flex items-center justify-between text-xs">
    <div class="flex items-center gap-1.5">
      {#if isApproximate && !isOverflow}
        <span class="text-tertiary">≈</span>
      {/if}
      <span>{formattedGrandTotal} / {formattedLimit} {m.tokens().toLowerCase()}</span>

      <!-- Legend indicators for segments -->
      {#if combinedHistoryTokens > 0 || tokens > 0}
        <div class="ml-2 flex items-center gap-2">
          {#if combinedHistoryTokens > 0}
            <div class="flex items-center gap-1">
              <div class="h-2 w-2 rounded-full {historySegmentColorClass}"></div>
              <span class="text-tertiary text-[10px]">{m.history_label()}</span>
            </div>
          {/if}
          {#if tokens > 0}
            <div class="flex items-center gap-1">
              <div class="h-2 w-2 rounded-full {newSegmentColorClass}"></div>
              <span class="text-tertiary text-[10px]">{m.new_label()}</span>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <div class="flex items-center gap-3">
      {#if isOverflow}
        <Tooltip text={m.context_limit_exceeded()} placement="top" let:trigger asFragment>
          <Button
            unstyled
            is={trigger}
            class="hover:bg-negative-dimmer/60 -m-1 flex cursor-help items-center gap-1 rounded-md p-1 transition-colors duration-200"
          >
            <AlertTriangle class="text-negative-stronger h-4 w-4 flex-shrink-0" />
            <span class="text-negative-stronger font-medium">({formattedOverflow} {m.over()})</span>
          </Button>
        </Tooltip>
      {/if}

      <span
        class={isOverflow
          ? "text-negative-stronger font-bold"
          : totalPercentage > 85
            ? "text-warning font-medium"
            : ""}>{totalPercentage.toFixed(1)}%</span
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
