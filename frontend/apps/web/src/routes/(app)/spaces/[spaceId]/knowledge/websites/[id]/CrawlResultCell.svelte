<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    getCrawlOutcome,
    getCrawlOutcomeLabel,
    getCrawlOutcomeTooltip,
    getCrawlRunResultLabels,
    isDuplicateCrawlSkip
  } from "$lib/features/knowledge/crawlOutcomePresentation";

  export let crawl: CrawlRun;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  function crawlStatus(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const reason = crawl.result_location ?? undefined;
    const outcome = getCrawlOutcome(crawl);
    const outcomeTooltip = getCrawlOutcomeTooltip(outcome, m.crawl_failed());
    const isDuplicateSkip = isDuplicateCrawlSkip(outcome);
    const skipTooltip = isDuplicateSkip ? m.crawl_skipped_duplicate() : (outcomeTooltip ?? reason);
    if (crawl.status === "failed" && isDuplicateSkip) {
      return {
        color: "gray",
        label: m.crawl_skipped(),
        tooltip: skipTooltip
      };
    }

    if (crawl.status === "failed" || crawl.status === "not found") {
      return {
        color: "orange",
        label: outcome ? getCrawlOutcomeLabel(outcome, m.crawl_failed()) : m.crawl_failed(),
        tooltip: outcomeTooltip ?? reason
      };
    }

    if (crawl.status === "queued") {
      return {
        color: "blue",
        label: m.queued()
      };
    }

    if (crawl.status === "in progress") {
      return {
        color: "yellow",
        label: m.in_progress()
      };
    }

    return {
      color: "blue",
      label: m.crawl_still_running()
    };
  }
</script>

<div class="flex w-full flex-wrap items-center gap-2 {cls}" style="justify-content: flex-{align}">
  {#if crawl.status === "complete"}
    {@const resultLabels = getCrawlRunResultLabels(crawl)}
    {#if resultLabels.length > 0}
      {#each resultLabels as resultLabel (resultLabel.label)}
        <Label.Single capitalize={false} item={resultLabel}></Label.Single>
      {/each}
    {:else}
      {@const outcome = getCrawlOutcome(crawl)}
      <Label.Single
        capitalize={false}
        item={{
          color: "green",
          label: outcome ? getCrawlOutcomeLabel(outcome, m.complete()) : m.complete(),
          tooltip: getCrawlOutcomeTooltip(outcome, m.complete())
        }}
      ></Label.Single>
    {/if}
  {:else}
    <Label.Single capitalize={false} item={crawlStatus()}></Label.Single>
  {/if}
</div>
