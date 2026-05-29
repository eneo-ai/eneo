<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  interface Props {
    overflowTokens: number;
  }

  const { overflowTokens }: Props = $props();

  // Format overflow tokens for display
  const formattedOverflow = $derived(overflowTokens.toLocaleString());
</script>

<div class="flex max-w-xs flex-col gap-2 p-1 text-sm">
  <div class="font-semibold text-white">{m.token_context_limit_exceeded()}</div>
  <hr class="border-white/20" />
  <p class="leading-snug text-slate-300">
    {m.token_over_limit_prefix()}
    <strong class="text-negative-default font-bold">{formattedOverflow}</strong>
    {m.token_over_limit_suffix()}
  </p>
</div>
