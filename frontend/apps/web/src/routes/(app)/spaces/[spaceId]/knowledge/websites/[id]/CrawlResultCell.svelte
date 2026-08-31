<script lang="ts">
  import type { CrawlRun } from "@eneo/eneo-js";
  import { Label } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import {
    crawlRunFailureMessage,
    crawlRunState,
    crawlRunStateLabel,
    type CrawlRunState
  } from "$lib/features/knowledge/crawlRunState";

  export let crawl: CrawlRun;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  $: pagesCrawled = crawl.pages_crawled ?? 0;
  $: filesDownloaded = crawl.files_downloaded ?? 0;
  $: pagesFailed = crawl.pages_failed ?? 0;
  $: filesFailed = crawl.files_failed ?? 0;
  $: state = crawlRunState(crawl);

  function getFailureReasonLabel(reason: string): string {
    const normalizedReason = reason
      .replace(/^_/, "")
      .replace(/([a-z])([A-Z])/g, "$1_$2")
      .toLowerCase();
    const labels: Record<string, () => string> = {
      empty_content: () => m.failure_reason_EMPTY_CONTENT(),
      no_chunks: () => m.failure_reason_NO_CHUNKS(),
      embedding_timeout: () => m.failure_reason_EMBEDDING_TIMEOUT(),
      embedding_error: () => m.failure_reason_EMBEDDING_ERROR(),
      db_error: () => m.failure_reason_DB_ERROR(),
      no_embedding_model: () => m.failure_reason_NO_EMBEDDING_MODEL(),
      missing_provider: () => m.failure_reason_MISSING_PROVIDER(),
      redirect_rejected: () => m.failure_reason_redirect_rejected(),
      unsafe_target: () => m.failure_reason_unsafe_target(),
      request_timeout: () => m.failure_reason_timeout(),
      connection_error: () => m.failure_reason_connection(),
      response_decode_error: () => m.failure_reason_invalid_response(),
      request_failed: () => m.failure_reason_other(),
      invalid_sitemap: () => m.failure_reason_invalid_sitemap(),
      sitemap_too_large: () => m.failure_reason_too_large(),
      response_too_large: () => m.failure_reason_too_large(),
      file_too_large: () => m.failure_reason_too_large(),
      unsupported_content_type: () => m.failure_reason_unsupported_content(),
      robots_disallowed: () => m.failure_reason_robots_disallowed(),
      file_out_of_scope: () => m.failure_reason_file_out_of_scope()
    };
    if (/^http_\d{3}$/.test(normalizedReason)) {
      return m.failure_reason_http({ status: normalizedReason.slice(5) });
    }
    return labels[normalizedReason]?.() ?? m.failure_reason_other();
  }

  function getFailureTooltip(): string | undefined {
    const summary = crawl.failure_summary;
    if (!summary || Object.keys(summary).length === 0) {
      return undefined;
    }

    const lines = Object.entries(summary)
      .map(([reason, count]) => `${getFailureReasonLabel(reason)}: ${count}`)
      .join("\n");

    return `${m.failure_reasons_tooltip()}:\n${lines}`;
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

  function crawlStatus(currentState: CrawlRunState): {
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
          ? crawlRunFailureMessage(crawl)
          : undefined
    };
  }
</script>

<div class="flex w-full items-center gap-2 {cls}" style="justify-content: flex-{align}">
  {#if state === "succeeded" || state === "partial" || state === "running" || state === "finalizing" || state === "stopping"}
    {#if pagesCrawled || filesDownloaded}
      <Label.Single capitalize={false} item={successLabel()}></Label.Single>
    {/if}
    {#if pagesFailed || filesFailed}
      <Label.Single capitalize={false} item={failedLabel()}></Label.Single>
    {/if}
    {#if !pagesCrawled && !filesDownloaded && !pagesFailed && !filesFailed}
      <Label.Single capitalize={false} item={crawlStatus(state)}></Label.Single>
    {/if}
  {:else}
    <Label.Single capitalize={false} item={crawlStatus(state)}></Label.Single>
  {/if}
</div>
