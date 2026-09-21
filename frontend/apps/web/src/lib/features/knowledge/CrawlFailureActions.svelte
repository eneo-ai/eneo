<script lang="ts">
  import type { CrawlResourceFailure, CrawlRun } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { hasCrawlIssues } from "./crawlRunState";

  let {
    run,
    onselect
  }: {
    run: CrawlRun;
    onselect: (kind: CrawlResourceFailure["kind"] | null) => void;
  } = $props();
</script>

{#if hasCrawlIssues(run)}
  <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
    {#if run.pages_failed || run.files_failed}<span class="text-secondary"
        >{m.crawl_not_indexed()}</span
      >{/if}
    {#if (run.pages_failed ?? 0) > 0}
      <Button
        variant="link"
        size="sm"
        class="text-accent-stronger px-1 text-xs underline"
        onclick={() => onselect("page")}
        aria-label={m.crawl_view_failed_pages({ count: run.pages_failed ?? 0 })}
      >
        {m.crawl_failed_pages_count({ count: run.pages_failed ?? 0 })}
      </Button>
    {/if}
    {#if (run.files_failed ?? 0) > 0}
      <Button
        variant="link"
        size="sm"
        class="text-accent-stronger px-1 text-xs underline"
        onclick={() => onselect("file")}
        aria-label={m.crawl_view_failed_files({ count: run.files_failed ?? 0 })}
      >
        {m.crawl_failed_files_count({ count: run.files_failed ?? 0 })}
      </Button>
    {/if}
    {#if !(run.pages_failed || run.files_failed) && hasCrawlIssues(run)}
      <Button
        variant="link"
        size="sm"
        class="text-accent-stronger px-1 text-xs underline"
        onclick={() => onselect(null)}
      >
        {m.crawl_view_errors()}
      </Button>
    {/if}
  </div>
{/if}
