<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let crawl: CrawlRun;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  type CrawlOutcome = {
    code: string;
    severity: "info" | "warning" | "error";
    message_key: string;
    detail?: string | null;
    affected_count?: number | null;
  };
  type CrawlRunWithOutcome = CrawlRun & { outcome?: CrawlOutcome | null };

  const successPages = (crawl.pages_crawled ?? 0) - (crawl.pages_failed ?? 0);
  const successFiles = (crawl.files_downloaded ?? 0) - (crawl.files_failed ?? 0);

  // Map failure reason codes to i18n labels
  function getFailureReasonLabel(reason: string): string {
    const labels: Record<string, () => string> = {
      EMPTY_CONTENT: () => m.failure_reason_EMPTY_CONTENT(),
      NO_CHUNKS: () => m.failure_reason_NO_CHUNKS(),
      EMBEDDING_TIMEOUT: () => m.failure_reason_EMBEDDING_TIMEOUT(),
      EMBEDDING_ERROR: () => m.failure_reason_EMBEDDING_ERROR(),
      EMBEDDING_BATCH_LIMIT: () => m.failure_reason_EMBEDDING_BATCH_LIMIT(),
      DB_ERROR: () => m.failure_reason_DB_ERROR(),
      NO_EMBEDDING_MODEL: () => m.failure_reason_NO_EMBEDDING_MODEL(),
      MISSING_PROVIDER: () => m.failure_reason_MISSING_PROVIDER()
    };
    return labels[reason]?.() ?? reason;
  }

  function getOutcome(): CrawlOutcome | undefined {
    return (crawl as CrawlRunWithOutcome).outcome ?? undefined;
  }

  function getOutcomeLabel(outcome: CrawlOutcome): string {
    const labels: Record<string, () => string> = {
      crawl_outcome_duplicate_skipped: () => m.crawl_outcome_duplicate_skipped(),
      crawl_outcome_embedding_config_missing: () => m.crawl_outcome_embedding_config_missing(),
      crawl_outcome_no_pages_returned: () => m.crawl_outcome_no_pages_returned(),
      crawl_outcome_timeout_no_pages: () => m.crawl_outcome_timeout_no_pages(),
      crawl_outcome_page_failures: () => m.crawl_outcome_page_failures(),
      crawl_outcome_unknown_error: () => m.crawl_outcome_unknown_error()
    };
    return labels[outcome.message_key]?.() ?? outcome.detail ?? m.crawl_failed();
  }

  function getOutcomeTooltip(): string | undefined {
    const outcome = getOutcome();
    if (!outcome) {
      return undefined;
    }

    const label = getOutcomeLabel(outcome);
    const affected = outcome.affected_count
      ? `\n${m.crawl_outcome_affected_count({ count: outcome.affected_count })}`
      : "";
    const detail = outcome.detail ? `\n${outcome.detail}` : "";
    return `${label}${affected}${detail}`;
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

  function crawlStatus(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const reason = crawl.result_location ?? undefined;
    const outcome = getOutcome();
    const outcomeTooltip = getOutcomeTooltip();
    const isDuplicateSkip = outcome?.code === "CRAWL_DUPLICATE_SKIPPED";
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
        label: outcome ? getOutcomeLabel(outcome) : m.crawl_failed(),
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
