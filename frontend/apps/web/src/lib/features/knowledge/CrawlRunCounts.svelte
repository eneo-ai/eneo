<script lang="ts">
  import type { CrawlResourceFailure, CrawlRun } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { cn } from "$lib/utils";

  let {
    run,
    onshowFailures
  }: { run: CrawlRun; onshowFailures?: (kind: CrawlResourceFailure["kind"]) => void } = $props();
  const columns = $derived([
    { key: "updated" as const, label: m.crawl_counts_succeeded() },
    { key: "unchanged" as const, label: m.crawl_counts_unchanged() },
    { key: "failed" as const, label: m.crawl_counts_failed() }
  ]);
  const rows = $derived([
    {
      kind: "page" as const,
      label: m.crawl_counts_pages(),
      updated: run.pages_crawled,
      unchanged: run.pages_unchanged,
      failed: run.pages_failed
    },
    {
      kind: "file" as const,
      label: m.crawl_counts_files(),
      updated: run.files_downloaded,
      unchanged: run.files_unchanged,
      failed: run.files_failed
    }
  ]);
</script>

<table class="w-full text-xs tabular-nums">
  <caption class="sr-only">{m.crawl_counts_caption()}</caption>
  <thead class="text-secondary">
    <tr>
      <td></td>
      {#each columns as column (column.key)}
        <th scope="col" class="pb-1 pl-3 text-right font-normal">{column.label}</th>
      {/each}
    </tr>
  </thead>
  <tbody>
    {#each rows as row (row.label)}
      <tr>
        <th scope="row" class="py-0.5 text-left font-normal">{row.label}</th>
        {#each columns as column (column.key)}
          {@const count = row[column.key]}
          {@const failedColumn = column.key === "failed"}
          <td
            class={cn(
              "py-0.5 pl-3 text-right",
              failedColumn && count != null && count > 0 && "text-negative-stronger font-medium",
              column.key === "unchanged" && "text-secondary"
            )}
          >
            {#if count == null}
              <span aria-hidden="true">—</span><span class="sr-only"
                >{m.crawl_counts_unknown()}</span
              >
            {:else if failedColumn && count > 0 && onshowFailures}
              <Button
                variant="link"
                size="sm"
                class="text-accent-stronger min-w-7 px-1 text-xs underline"
                onclick={() => onshowFailures?.(row.kind)}
                aria-label={row.kind === "page"
                  ? m.crawl_view_failed_pages({ count })
                  : m.crawl_view_failed_files({ count })}
              >
                {count.toLocaleString(getLocale())}
              </Button>
            {:else}{count.toLocaleString(getLocale())}{/if}
          </td>
        {/each}
      </tr>
    {/each}
  </tbody>
</table>
