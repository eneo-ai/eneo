<script lang="ts">
  import type { CrawlRun } from "@eneo/eneo-js";
  import { Label } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";

  export let crawl: CrawlRun;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  $: pagesCrawled = crawl.pages_crawled ?? 0;
  $: filesDownloaded = crawl.files_downloaded ?? 0;
  $: pagesFailed = crawl.pages_failed ?? 0;
  $: filesFailed = crawl.files_failed ?? 0;
  $: successPages = pagesCrawled - pagesFailed;
  $: successFiles = filesDownloaded - filesFailed;
  const SKIPPED_PREFIX = "skipped duplicate crawl";

  // Map failure reason codes to i18n labels
  function getFailureReasonLabel(reason: string): string {
    const labels: Record<string, () => string> = {
      EMPTY_CONTENT: () => m.failure_reason_EMPTY_CONTENT(),
      NO_CHUNKS: () => m.failure_reason_NO_CHUNKS(),
      EMBEDDING_TIMEOUT: () => m.failure_reason_EMBEDDING_TIMEOUT(),
      EMBEDDING_ERROR: () => m.failure_reason_EMBEDDING_ERROR(),
      DB_ERROR: () => m.failure_reason_DB_ERROR(),
      NO_EMBEDDING_MODEL: () => m.failure_reason_NO_EMBEDDING_MODEL(),
      MISSING_PROVIDER: () => m.failure_reason_MISSING_PROVIDER()
    };
    return labels[reason]?.() ?? reason;
  }

  // Build tooltip content from failure_summary
  function getFailureTooltip(): string | undefined {
    const summary = (crawl as CrawlRun & { failure_summary?: Record<string, number> })
      .failure_summary;
    if (!summary || Object.keys(summary).length === 0) {
      return undefined;
    }

    const lines = Object.entries(summary)
      .map(([reason, count]) => `${getFailureReasonLabel(reason)}: ${count}`)
      .join("\n");

    return `${m.failure_reasons_tooltip()}:\n${lines}`;
  }

  function totalLabel(): { label: string; color: Label.LabelColor } {
    if (filesDownloaded > 0) {
      return {
        color: "blue",
        label: m.crawled_pages_and_files({
          pages: pagesCrawled,
          files: filesDownloaded
        })
      };
    } else {
      return {
        color: "blue",
        label: m.crawled_pages({ count: pagesCrawled })
      };
    }
  }

  function failedLabel(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const tooltip = getFailureTooltip();

    if (pagesFailed && filesFailed) {
      return {
        color: "orange",
        label: m.pages_and_files_failed({ pages: pagesFailed, files: filesFailed }),
        tooltip
      };
    } else if (pagesFailed) {
      return {
        color: "orange",
        label: m.pages_failed({ count: pagesFailed }),
        tooltip
      };
    } else {
      return {
        color: "orange",
        label: m.files_failed({ count: filesFailed }),
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

  function crawlStatus(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const reason = crawl.result_location ?? undefined;
    const skipTooltip = crawl.result_location?.toLowerCase().startsWith(SKIPPED_PREFIX)
      ? m.crawl_skipped_duplicate()
      : reason;
    if (
      crawl.status === "failed" &&
      crawl.result_location?.toLowerCase().startsWith(SKIPPED_PREFIX)
    ) {
      return {
        color: "gray",
        label: m.crawl_skipped(),
        tooltip: skipTooltip
      };
    }

    if (crawl.status === "failed" || crawl.status === "not found") {
      return {
        color: "orange",
        label: m.crawl_failed(),
        tooltip: reason
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
    <Label.Single capitalize={false} item={totalLabel()}></Label.Single>
    {#if successPages || successFiles}
      <Label.Single capitalize={false} item={successLabel()}></Label.Single>
    {/if}
    {#if crawl.pages_failed || crawl.files_failed}
      <Label.Single capitalize={false} item={failedLabel()}></Label.Single>
    {/if}
  {:else}
    <Label.Single capitalize={false} item={crawlStatus()}></Label.Single>
  {/if}
</div>
