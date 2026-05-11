<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    getCrawlOutcome,
    getCrawlOutcomeLabel,
    getCrawlOutcomeTooltip,
    getFailureSummaryTooltip,
    isDuplicateCrawlSkip,
    isSourceRetentionOnly
  } from "$lib/features/knowledge/crawlOutcomePresentation";

  export let crawl: CrawlRun;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  const successPages = (crawl.pages_crawled ?? 0) - (crawl.pages_failed ?? 0);
  const successFiles = (crawl.files_downloaded ?? 0) - (crawl.files_failed ?? 0);

  function getFailureTooltip(): string | undefined {
    return getFailureSummaryTooltip(crawl.failure_summary);
  }

  function totalLabel(): { label: string; color: Label.LabelColor } {
    if ((crawl.files_downloaded ?? 0) > 0) {
      return {
        color: "blue",
        label: m.crawled_pages_and_files({
          pages: crawl.pages_crawled,
          files: crawl.files_downloaded
        })
      };
    } else {
      return {
        color: "blue",
        label: m.crawled_pages({ count: crawl.pages_crawled })
      };
    }
  }

  function failedLabel(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const tooltip = getFailureTooltip();

    if (crawl.pages_failed && crawl.files_failed) {
      return {
        color: "orange",
        label: m.pages_and_files_failed({ pages: crawl.pages_failed, files: crawl.files_failed }),
        tooltip
      };
    } else if (crawl.pages_failed) {
      return {
        color: "orange",
        label: m.pages_failed({ count: crawl.pages_failed }),
        tooltip
      };
    } else {
      return {
        color: "orange",
        label: m.files_failed({ count: crawl.files_failed }),
        tooltip
      };
    }
  }

  function successLabel(): { label: string; color: Label.LabelColor } {
    if (successPages && successFiles) {
      return {
        color: "green",
        label: m.pages_and_files_succeeded({ pages: successPages, files: successFiles })
      };
    } else if (successPages > 0) {
      return {
        color: "green",
        label: m.pages_succeeded({ count: successPages })
      };
    } else {
      return {
        color: "green",
        label: m.files_succeeded({ count: successFiles })
      };
    }
  }

  function sourceRetentionLabel(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const outcome = getCrawlOutcome(crawl);
    return {
      color: "green",
      label: outcome ? getCrawlOutcomeLabel(outcome, m.complete()) : m.complete(),
      tooltip: getCrawlOutcomeTooltip(outcome, m.complete())
    };
  }

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

<div class="flex w-full items-center gap-2 {cls}" style="justify-content: flex-{align}">
  {#if crawl.status === "complete"}
    {#if isSourceRetentionOnly(getCrawlOutcome(crawl))}
      <Label.Single capitalize={false} item={sourceRetentionLabel()}></Label.Single>
    {:else}
      <Label.Single capitalize={false} item={totalLabel()}></Label.Single>
      {#if successPages || successFiles}
        <Label.Single capitalize={false} item={successLabel()}></Label.Single>
      {/if}
      {#if crawl.pages_failed || crawl.files_failed}
        <Label.Single capitalize={false} item={failedLabel()}></Label.Single>
      {/if}
    {/if}
  {:else}
    <Label.Single capitalize={false} item={crawlStatus()}></Label.Single>
  {/if}
</div>
