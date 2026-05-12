<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import * as Card from "$lib/components/ui/card/index.js";
  import StatusBadge from "$lib/components/StatusBadge.svelte";
  import { getCrawlRunStatus } from "$lib/features/knowledge/crawlStatusPresentation";
  import { getCrawlRunCountBreakdown } from "$lib/features/knowledge/crawlOutcomePresentation";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import "dayjs/locale/sv";
  import "dayjs/locale/en";

  dayjs.extend(relativeTime);

  type Props = { runs: CrawlRun[] };
  let { runs }: Props = $props();

  $effect.pre(() => {
    dayjs.locale(getLocale());
  });

  const totalRuns = $derived(runs.length);
  const latest = $derived<CrawlRun | undefined>(runs[0]);
  const lastSuccess = $derived<CrawlRun | undefined>(runs.find((r) => r.status === "complete"));

  const latestStatus = $derived(getCrawlRunStatus(latest));
  const latestRelative = $derived(latest ? dayjs(latest.created_at).fromNow() : null);

  // "Last indexed" counts pages/files present in the index — both newly inserted
  // and items kept via hash-skip — since both are queryable from the user's POV.
  const lastIndexedSummary = $derived.by(() => {
    if (!lastSuccess) return null;
    const breakdown = getCrawlRunCountBreakdown(lastSuccess);
    const pages = (breakdown.pages_indexed ?? 0) + (breakdown.pages_hash_retained ?? 0);
    const files = (breakdown.files_indexed ?? 0) + (breakdown.files_hash_retained ?? 0);
    if (pages === 0 && files === 0) return null;
    const finishedAt = lastSuccess.finished_at;
    const relative = finishedAt ? dayjs(finishedAt).fromNow() : null;
    const counts =
      files > 0
        ? m.crawl_overview_pages_files({ pages, files })
        : m.crawl_overview_pages_only({ pages });
    return { counts, relative };
  });
</script>

<Card.Root class="my-3 mr-3 ml-0" aria-label={m.crawl_overview_total_runs()}>
  <Card.Content class="grid grid-cols-1 gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
    <div class="flex flex-col gap-2">
      <span class="text-secondary text-sm">{m.crawl_overview_last_run()}</span>
      {#if latest}
        <StatusBadge tone={latestStatus.tone} tooltip={latestStatus.tooltip}>
          {latestStatus.label}
        </StatusBadge>
        {#if latestRelative}
          <span class="text-secondary text-xs">{latestRelative}</span>
        {/if}
      {:else}
        <span class="text-primary text-base font-semibold">—</span>
      {/if}
    </div>

    <div class="flex flex-col gap-2">
      <span class="text-secondary text-sm">{m.crawl_overview_last_indexed()}</span>
      {#if lastIndexedSummary}
        <span class="text-primary text-base font-semibold tabular-nums">
          {lastIndexedSummary.counts}
        </span>
        {#if lastIndexedSummary.relative}
          <span class="text-secondary text-xs">{lastIndexedSummary.relative}</span>
        {/if}
      {:else}
        <span class="text-primary text-base font-semibold">
          {m.crawl_overview_never_indexed()}
        </span>
      {/if}
    </div>

    <div class="flex flex-col gap-2">
      <span class="text-secondary text-sm">{m.crawl_overview_total_runs()}</span>
      <span class="text-primary text-base font-semibold tabular-nums">
        {totalRuns}
      </span>
    </div>
  </Card.Content>
</Card.Root>

{#if totalRuns === 0}
  <p class="text-secondary mr-3 mb-4 ml-0 text-sm">
    {m.crawl_overview_no_runs()}
  </p>
{/if}
