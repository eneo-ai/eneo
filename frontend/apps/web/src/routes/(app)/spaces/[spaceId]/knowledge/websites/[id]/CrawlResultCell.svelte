<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import StatusBadge from "$lib/components/StatusBadge.svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    getCrawlOutcome,
    getCrawlOutcomeLabel,
    getCrawlOutcomeTooltip,
    getCrawlRunResultLabels
  } from "$lib/features/knowledge/crawlOutcomePresentation";
  import {
    getCrawlRunStatus,
    labelColorToTone
  } from "$lib/features/knowledge/crawlStatusPresentation";

  export let crawl: CrawlRun;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  $: resultLabels = getCrawlRunResultLabels(crawl);
  $: outcome = getCrawlOutcome(crawl);
  $: nonCompleteStatus = getCrawlRunStatus(crawl);
</script>

<div
  class="flex w-full flex-wrap items-center gap-x-2.5 gap-y-1.5 py-1.5 {cls}"
  style="justify-content: flex-{align}"
>
  {#if crawl.status === "complete"}
    {#if resultLabels.length > 0}
      {#each resultLabels as resultLabel (resultLabel.label)}
        <StatusBadge tone={labelColorToTone(resultLabel.color)} tooltip={resultLabel.tooltip}>
          {resultLabel.label}
        </StatusBadge>
      {/each}
    {:else}
      <StatusBadge tone="positive" tooltip={getCrawlOutcomeTooltip(outcome, m.complete())}>
        {outcome ? getCrawlOutcomeLabel(outcome, m.complete()) : m.complete()}
      </StatusBadge>
    {/if}
  {:else}
    <StatusBadge tone={nonCompleteStatus.tone} tooltip={nonCompleteStatus.tooltip}>
      {nonCompleteStatus.label}
    </StatusBadge>
  {/if}
</div>
