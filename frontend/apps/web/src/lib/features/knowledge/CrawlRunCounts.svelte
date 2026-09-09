<script lang="ts">
  import type { CrawlRun } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { cn } from "$lib/utils";

  let { run }: { run: CrawlRun } = $props();
  const rows = $derived([
    { label: m.crawl_counts_pages(), succeeded: run.pages_crawled, failed: run.pages_failed },
    { label: m.crawl_counts_files(), succeeded: run.files_downloaded, failed: run.files_failed }
  ]);
</script>

<table class="w-full text-xs tabular-nums">
  <caption class="sr-only">{m.crawl_counts_caption()}</caption>
  <thead class="text-secondary">
    <tr>
      <td></td>
      <th scope="col" class="pb-1 pl-3 text-right font-normal">{m.crawl_counts_succeeded()}</th>
      <th scope="col" class="pb-1 pl-3 text-right font-normal">{m.crawl_counts_failed()}</th>
    </tr>
  </thead>
  <tbody>
    {#each rows as row (row.label)}
      <tr>
        <th scope="row" class="py-0.5 text-left font-normal">{row.label}</th>
        {#each [row.succeeded, row.failed] as count, column (column)}
          <td
            class={cn(
              "py-0.5 pl-3 text-right",
              column === 1 && count != null && count > 0 && "text-negative-default font-medium"
            )}
          >
            {#if count == null}
              <span aria-hidden="true">—</span><span class="sr-only"
                >{m.crawl_counts_unknown()}</span
              >
            {:else}{count.toLocaleString(getLocale())}{/if}
          </td>
        {/each}
      </tr>
    {/each}
  </tbody>
</table>
