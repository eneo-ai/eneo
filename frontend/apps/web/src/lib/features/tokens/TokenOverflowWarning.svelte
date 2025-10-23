<script lang="ts">
  interface Props {
    overflowTokens: number;
  }

  const { overflowTokens }: Props = $props();

  // Format overflow tokens for display
  const formattedOverflow = $derived(overflowTokens.toLocaleString());
</script>

<div class="flex max-w-xs flex-col gap-2 p-1 text-sm">
  <div class="font-semibold text-white">Context Limit Exceeded</div>
  <hr class="border-white/20" />
  <p class="leading-snug text-slate-300">
    You are over the limit by
    <strong class="font-bold text-negative-default">{formattedOverflow}</strong>
    tokens. Older messages or file content may be truncated.
  </p>
</div>