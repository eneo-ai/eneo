<script lang="ts">
  interface Props {
    tokens: number;
    limit: number;
    isApproximate?: boolean;
  }

  const { tokens = 0, limit = 128000, isApproximate = false }: Props = $props();

  // Calculate percentage with safety checks
  const percentage = $derived(limit > 0 ? Math.min((tokens / limit) * 100, 100) : 0);

  // Determine color based on percentage
  const colorClass = $derived(
    percentage < 70 ? 'bg-green-500' :
    percentage < 85 ? 'bg-yellow-500' :
    percentage < 95 ? 'bg-orange-500' :
    'bg-red-500'
  );

  // Format numbers with locale-aware thousands separators
  const formattedTokens = $derived(tokens.toLocaleString());
  const formattedLimit = $derived(limit.toLocaleString());
</script>

<div class="token-usage-bar w-full">
  <!-- Progress bar -->
  <div class="relative h-1.5 w-full bg-tertiary rounded-full overflow-hidden mb-1">
    <div
      class="absolute left-0 top-0 h-full transition-all duration-300 ease-out rounded-full {colorClass}"
      style="width: {percentage}%"
    ></div>
  </div>

  <!-- Text display -->
  <div class="flex items-center justify-between text-xs text-secondary">
    <div class="flex items-center gap-1">
      {#if isApproximate}
        <span class="text-tertiary">≈</span>
      {/if}
      <span>{formattedTokens} / {formattedLimit} tokens</span>
    </div>
    <span class="{percentage > 85 ? 'text-warning font-medium' : ''}">{percentage.toFixed(1)}%</span>
  </div>
</div>

<style>
  .token-usage-bar {
    /* Ensures smooth animations */
    will-change: width;
  }
</style>