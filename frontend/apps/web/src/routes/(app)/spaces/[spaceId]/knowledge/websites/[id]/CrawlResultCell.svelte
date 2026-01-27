<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let crawl: CrawlRun;
  export let align: "start" | "end" | "center" = "start";

  let cls = "";
  export { cls as class };

  const successPages = (crawl.pages_crawled ?? 0) - (crawl.pages_failed ?? 0);
  const successFiles = (crawl.files_downloaded ?? 0) - (crawl.files_failed ?? 0);
  const SKIPPED_PREFIX = "skipped duplicate crawl";

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

  function failedLabel(): { label: string; color: Label.LabelColor } {
    if (crawl.pages_failed && crawl.files_failed) {
      return {
        color: "orange",
        label: m.pages_and_files_failed({ pages: crawl.pages_failed, files: crawl.files_failed })
      };
    } else if (crawl.pages_failed) {
      return {
        color: "orange",
        label: m.pages_failed({ count: crawl.pages_failed })
      };
    } else {
      return {
        color: "orange",
        label: m.files_failed({ count: crawl.files_failed })
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
