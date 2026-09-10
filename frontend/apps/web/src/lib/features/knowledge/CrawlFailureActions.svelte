<script lang="ts">
  import type { CrawlResourceFailure, CrawlRun } from "@eneo/eneo-js";
  import { ArrowRight } from "lucide-svelte";
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
  <div class="flex flex-wrap items-center gap-2">
    {#if (run.pages_failed ?? 0) > 0}
      <Button
        variant="outline"
        size="sm"
        class="text-negative-stronger"
        onclick={() => onselect("page")}
      >
        {m.crawl_view_failed_pages({ count: run.pages_failed ?? 0 })}<ArrowRight
          data-icon="inline-end"
        />
      </Button>
    {/if}
    {#if (run.files_failed ?? 0) > 0}
      <Button
        variant="outline"
        size="sm"
        class="text-negative-stronger"
        onclick={() => onselect("file")}
      >
        {m.crawl_view_failed_files({ count: run.files_failed ?? 0 })}<ArrowRight
          data-icon="inline-end"
        />
      </Button>
    {/if}
    {#if !(run.pages_failed || run.files_failed) && hasCrawlIssues(run)}
      <Button variant="outline" size="sm" onclick={() => onselect(null)}>
        {m.crawl_view_errors()}<ArrowRight data-icon="inline-end" />
      </Button>
    {/if}
  </div>
{/if}
