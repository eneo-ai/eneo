<script lang="ts">
  import type { CrawlRun } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button";
  import { formatDate, formatDuration, formatTime } from "$lib/core/formatting/dateTime";
  import SourceActivityDay from "$lib/features/knowledge/components/SourceActivityDay.svelte";
  import CrawlRunStatus from "$lib/features/knowledge/CrawlRunStatus.svelte";
  import {
    crawlRunFailureMessage,
    hasCrawlIssues,
    isActiveCrawlRun
  } from "$lib/features/knowledge/crawlRunState";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  let {
    runs,
    onshowProblems
  }: {
    runs: CrawlRun[];
    onshowProblems: (run: CrawlRun) => void;
  } = $props();

  const days = $derived.by(() => {
    const grouped: { date: CrawlRun["created_at"]; runs: CrawlRun[] }[] = [];
    for (const run of runs) {
      const previous = grouped.at(-1);
      if (previous && formatDate(previous.date) === formatDate(run.created_at)) {
        previous.runs.push(run);
      } else {
        grouped.push({ date: run.created_at, runs: [run] });
      }
    }
    return grouped;
  });

  function count(value: number | null | undefined): string {
    return value == null ? m.crawl_counts_unknown() : value.toLocaleString(getLocale());
  }
</script>

<section aria-label={m.source_tab_activity()} class="flex w-full flex-col gap-6 py-5 pr-4">
  {#if runs.length === 0}
    <p class="text-secondary py-6 text-sm">{m.this_website_not_crawled_before()}</p>
  {/if}
  <!-- Legacy runs without a date all format to "", so the first run identifies the day. -->
  {#each days as day (day.runs[0].id)}
    <SourceActivityDay date={day.date}>
      {#each day.runs as run (run.id)}
        <li class="border-dimmer flex gap-3 border-t py-3">
          <time
            datetime={run.created_at}
            class="text-secondary w-11 shrink-0 pt-1 text-xs tabular-nums"
            >{formatTime(run.created_at) || "–"}</time
          >
          <div class="flex min-w-0 flex-1 flex-col gap-2">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <CrawlRunStatus {run} />
              {#if !isActiveCrawlRun(run) && hasCrawlIssues(run)}
                <Button
                  variant="link"
                  size="sm"
                  class="text-accent-stronger"
                  onclick={() => onshowProblems(run)}
                >
                  {m.website_source_see_problems()}
                </Button>
              {/if}
            </div>
            {#if !isActiveCrawlRun(run) && run.failure_code}
              <p class="text-secondary text-sm">{crawlRunFailureMessage(run)}</p>
            {/if}
            <p class="text-sm">
              {m.website_source_run_results({
                pages: count(run.pages_crawled),
                files: count(run.files_downloaded)
              })}
            </p>
            {#if run.pages_unchanged || run.files_unchanged}
              <p class="text-secondary text-sm">
                {m.website_source_run_unchanged({
                  pages: count(run.pages_unchanged),
                  files: count(run.files_unchanged)
                })}
              </p>
            {/if}
            <p class="text-secondary text-xs">
              {run.origin === "manual"
                ? m.crawl_origin_manual()
                : run.origin === "scheduled"
                  ? m.crawl_origin_scheduled()
                  : m.crawl_origin_legacy()}
              {#if run.finished_at && run.created_at}
                · {formatDuration(
                  new Date(run.finished_at).getTime() - new Date(run.created_at).getTime()
                )}
              {/if}
            </p>
          </div>
        </li>
      {/each}
    </SourceActivityDay>
  {/each}
</section>
