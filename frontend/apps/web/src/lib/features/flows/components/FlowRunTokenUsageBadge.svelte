<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import TokenUsageBadge from "./TokenUsageBadge.svelte";
  import {
    buildFlowRunTokenUsageView,
    formatFlowRunTokenCount,
    type FlowRunTokenUsagePayload
  } from "./flowRunTokenUsage";

  interface Props {
    tokenUsage?: FlowRunTokenUsagePayload | null;
    interactive?: boolean;
  }

  let { tokenUsage = null, interactive = true }: Props = $props();

  const usage = $derived.by(() => buildFlowRunTokenUsageView(tokenUsage));

  function format(value: number): string {
    return formatFlowRunTokenCount(value, getLocale());
  }
</script>

{#if usage.kind === "recorded"}
  <TokenUsageBadge
    total={format(usage.total)}
    input={format(usage.input)}
    output={format(usage.output)}
    note={m.flow_run_token_usage_provider_note()}
    incomplete={usage.incomplete}
    inputIncomplete={usage.inputIncomplete}
    outputIncomplete={usage.outputIncomplete}
    {interactive}
  />
{:else}
  <span class="text-muted text-xs">{m.flow_run_token_usage_not_recorded()}</span>
{/if}
