<script lang="ts">
  import type { CrawlRun, CrawlResourceFailure, Eneo } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import {
    crawlFailureReasonLabel,
    crawlRunFailureMessage,
    crawlRunState,
    crawlRunStateLabel,
    isActiveCrawlRun
  } from "$lib/features/knowledge/crawlRunState";

  const eneo = getEneo();
  let {
    run,
    open = false,
    onrefresh,
    fetchFailures = eneo.websites.crawlRuns.failures
  }: {
    run: CrawlRun;
    open?: boolean;
    onrefresh?: () => void | Promise<void>;
    fetchFailures?: Eneo["websites"]["crawlRuns"]["failures"];
  } = $props();
  const runId = $derived(run.id);
  let loadedRun = $state<CrawlRun | null>(null);
  let failures = $state<CrawlResourceFailure[]>([]);
  let total = $state(0);
  let nextCursor = $state<string | null>(null);
  let retryCursor = $state<string | null>(null);
  let detailsAvailable = $state(true);
  let loading = $state(false);
  let refreshing = $state(false);
  let loadFailed = $state(false);
  let generation = 0;
  const displayedRun = $derived(loadedRun ?? run);
  const summary = $derived(Object.entries(displayedRun.failure_summary ?? {}));

  async function loadFailures(cursor: string | null = null) {
    const request = ++generation;
    loading = true;
    loadFailed = false;
    retryCursor = cursor;
    try {
      const result = await fetchFailures({ id: runId, limit: 100, cursor });
      if (request !== generation) return;
      loadedRun = result.run;
      detailsAvailable = result.details_available;
      if (cursor === null) {
        failures = result.items;
      } else {
        const known = new Set(failures.map((failure) => failure.id));
        failures = [...failures, ...result.items.filter((failure) => !known.has(failure.id))];
      }
      total = result.total_count;
      nextCursor = result.next_cursor ?? null;
    } catch {
      if (request === generation) loadFailed = true;
    } finally {
      if (request === generation) loading = false;
    }
  }

  $effect(() => {
    const currentRun = run;
    if (open && currentRun.id) {
      untrack(() => {
        loadedRun = null;
        failures = [];
        total = 0;
        nextCursor = null;
        detailsAvailable = true;
        void loadFailures();
      });
    }
    return () => {
      generation += 1;
    };
  });

  function resourceLink(url: string): string | undefined {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : undefined;
    } catch {
      return undefined;
    }
  }

  async function refresh() {
    if (refreshing || loading) return;
    refreshing = true;
    try {
      if (onrefresh) await onrefresh();
      else await loadFailures();
    } finally {
      refreshing = false;
    }
  }
</script>

<div class="flex flex-col gap-2 pr-6">
  <p class="font-medium">{crawlRunStateLabel(crawlRunState(displayedRun))}</p>
  <div class="text-secondary flex flex-wrap gap-x-4 gap-y-1 text-sm">
    <span>{m.pages_succeeded({ count: displayedRun.pages_crawled ?? "—" })}</span>
    <span>{m.files_succeeded({ count: displayedRun.files_downloaded ?? "—" })}</span>
    <span>{m.pages_failed({ count: displayedRun.pages_failed ?? "—" })}</span>
    <span>{m.files_failed({ count: displayedRun.files_failed ?? "—" })}</span>
  </div>
  <p class="text-secondary text-sm">
    {displayedRun.origin === "manual"
      ? m.crawl_origin_manual()
      : displayedRun.origin === "scheduled"
        ? m.crawl_origin_scheduled()
        : m.crawl_origin_legacy()}
  </p>
  {#if displayedRun.failure_code}
    <p class="text-secondary text-sm">{crawlRunFailureMessage(displayedRun)}</p>
  {/if}
  {#if summary.length > 0}
    <ul class="text-secondary flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {#each summary as [reason, count] (reason)}
        <li>{crawlFailureReasonLabel(reason)}: {count}</li>
      {/each}
    </ul>
  {/if}
</div>

<div class="min-h-0 overflow-auto" aria-busy={loading}>
  {#if failures.length > 0}
    <table class="w-full table-fixed text-left text-sm">
      <thead class="border-default border-b">
        <tr>
          <th class="w-20 py-2 pr-3 font-medium">{m.crawl_failure_resource_type()}</th>
          <th class="py-2 pr-3 font-medium">{m.crawl_failure_address()}</th>
          <th class="w-1/3 py-2 font-medium">{m.crawl_failure_reason()}</th>
        </tr>
      </thead>
      <tbody>
        {#each failures as failure (failure.id)}
          {@const href = resourceLink(failure.url)}
          <tr class="border-default border-b last:border-0">
            <td class="py-3 pr-3 align-top"
              >{failure.kind === "page" ? m.page() : m.crawl_failure_file()}</td
            >
            <td class="py-3 pr-3 align-top break-all">
              {#if href}
                <!-- eslint-disable svelte/no-navigation-without-resolve -- validated external HTTP(S) address -->
                <a
                  {href}
                  target="_blank"
                  rel="noreferrer"
                  class="text-accent-default underline underline-offset-2">{failure.url}</a
                >
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
              {:else}
                {failure.url}
              {/if}
            </td>
            <td class="py-3 align-top break-words">{crawlFailureReasonLabel(failure.reason)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else if !loading && !loadFailed}
    <p class="text-secondary py-4 text-sm">
      {detailsAvailable ? m.crawl_failures_empty() : m.crawl_failures_unavailable()}
    </p>
  {/if}
</div>

{#if loading}
  <p role="status" class="text-secondary text-sm">{m.loading_more()}</p>
{/if}
{#if loadFailed}
  <div role="alert" class="flex items-center justify-between gap-3">
    <p class="text-negative-default text-sm">{m.crawl_failures_load_failed()}</p>
    <Button variant="outline" onclick={() => loadFailures(retryCursor)}>{m.retry()}</Button>
  </div>
{/if}
<div class="flex flex-wrap items-center justify-between gap-3">
  <div>
    {#if nextCursor && !loadFailed}
      <Button variant="outline" disabled={loading} onclick={() => loadFailures(nextCursor)}>
        {m.crawl_failures_load_more({ current: failures.length, total })}
      </Button>
    {/if}
  </div>
  <Button variant="outline" disabled={loading || refreshing} onclick={refresh}>{m.refresh()}</Button
  >
</div>
{#if isActiveCrawlRun(displayedRun)}
  <p class="text-secondary text-xs">{m.crawl_details_running()}</p>
{/if}
