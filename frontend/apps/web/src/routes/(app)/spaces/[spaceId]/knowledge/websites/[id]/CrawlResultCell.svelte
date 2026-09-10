<script lang="ts">
  import type { CrawlResourceFailure, CrawlRun } from "@eneo/eneo-js";
  import { Label } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    crawlRunFailureMessage,
    crawlRunState,
    crawlRunStateLabel,
    type CrawlRunState
  } from "$lib/features/knowledge/crawlRunState";

  import CrawlFailureActions from "$lib/features/knowledge/CrawlFailureActions.svelte";

  export let crawl: CrawlRun;
  export let onshowFailures: (kind: CrawlResourceFailure["kind"] | null) => void;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  $: pagesCrawled = crawl.pages_crawled ?? 0;
  $: filesDownloaded = crawl.files_downloaded ?? 0;
  $: pagesFailed = crawl.pages_failed ?? 0;
  $: filesFailed = crawl.files_failed ?? 0;
  $: state = crawlRunState(crawl);

  function successLabel(currentCrawl: CrawlRun): { label: string; color: Label.LabelColor } {
    const pagesCrawled = currentCrawl.pages_crawled ?? 0;
    const filesDownloaded = currentCrawl.files_downloaded ?? 0;
    if (pagesCrawled && filesDownloaded) {
      return {
        color: "green",
        label: m.pages_and_files_succeeded({ pages: pagesCrawled, files: filesDownloaded })
      };
    } else if (pagesCrawled > 0) {
      return {
        color: "green",
        label: m.pages_succeeded({ count: pagesCrawled })
      };
    } else {
      return {
        color: "green",
        label: m.files_succeeded({ count: filesDownloaded })
      };
    }
  }

  function crawlStatus(
    currentState: CrawlRunState,
    currentCrawl: CrawlRun
  ): {
    label: string;
    color: Label.LabelColor;
    tooltip?: string;
  } {
    return {
      color:
        currentState === "queued"
          ? "blue"
          : currentState === "cancelled" || currentState === "unchanged"
            ? "gray"
            : currentState === "failed" ||
                currentState === "interrupted" ||
                currentState === "unknown"
              ? "orange"
              : "yellow",
      label: crawlRunStateLabel(currentState),
      tooltip:
        currentState === "failed" || currentState === "interrupted" || currentState === "cancelled"
          ? crawlRunFailureMessage(currentCrawl)
          : undefined
    };
  }
</script>

<div class="flex w-full flex-wrap items-center gap-2 {cls}" style="justify-content: flex-{align}">
  {#if state === "succeeded" || state === "partial" || state === "running" || state === "finalizing" || state === "stopping"}
    {#if pagesCrawled || filesDownloaded}
      <Label.Single capitalize={false} item={successLabel(crawl)}></Label.Single>
    {/if}
    {#if !pagesCrawled && !filesDownloaded && !pagesFailed && !filesFailed}
      <Label.Single capitalize={false} item={crawlStatus(state, crawl)}></Label.Single>
    {/if}
  {:else}
    <Label.Single capitalize={false} item={crawlStatus(state, crawl)}></Label.Single>
  {/if}
  <CrawlFailureActions run={crawl} onselect={onshowFailures} />
</div>
