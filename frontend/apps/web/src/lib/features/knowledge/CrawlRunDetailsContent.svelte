<script lang="ts">
  import type { CrawlRun, CrawlResourceFailure, Eneo } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import { RefreshCw } from "lucide-svelte";
  import { cn } from "$lib/utils";
  import * as Table from "$lib/components/ui/table/index.js";
  import CrawlLoadError from "./CrawlLoadError.svelte";
  import CrawlRunCounts from "./CrawlRunCounts.svelte";
  import CrawlRunStatus from "./CrawlRunStatus.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import {
    crawlFailureReasonLabel,
    crawlRunFailureMessage,
    isActiveCrawlRun
  } from "$lib/features/knowledge/crawlRunState";

  const eneo = getEneo();
  let {
    run,
    open = false,
    onrefresh,
    onrunupdate,
    fetchFailures = eneo.websites.crawlRuns.failures
  }: {
    run: CrawlRun;
    open?: boolean;
    onrefresh?: () => void | Promise<void>;
    onrunupdate?: (run: CrawlRun) => void;
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
  let viewedRunId: string | null = null;
  const displayedRun = $derived(loadedRun ?? run);
  const summary = $derived(Object.entries(displayedRun.failure_summary ?? {}));

  async function loadFailures(cursor: string | null = null) {
    const request = ++generation;
    loading = true;
    retryCursor = cursor;
    try {
      const result = await fetchFailures({ id: runId, limit: 100, cursor });
      if (request !== generation) return;
      loadFailed = false;
      loadedRun = result.run;
      onrunupdate?.(loadedRun);
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
        // onrunupdate passes this exact proxy back through run. Keep its identity:
        // cloning it would turn snapshot adoption into another fetch/adopt cycle.
        if (currentRun === loadedRun) return;
        loadedRun = null;
        if (viewedRunId !== currentRun.id) {
          failures = [];
          total = 0;
          nextCursor = null;
          detailsAvailable = true;
          loadFailed = false;
        }
        viewedRunId = currentRun.id;
        void loadFailures();
      });
    } else {
      viewedRunId = null;
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

<div class="flex flex-col gap-3">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <CrawlRunStatus run={displayedRun} />
    <Button
      variant="outline"
      size="sm"
      disabled={loading || refreshing}
      aria-busy={loading || refreshing}
      onclick={refresh}
    >
      <RefreshCw
        data-icon="inline-start"
        class={cn((loading || refreshing) && "motion-safe:animate-spin")}
      />{m.refresh()}
    </Button>
  </div>
  <div class="max-w-sm"><CrawlRunCounts run={displayedRun} /></div>
  <p class="text-secondary text-sm">
    {displayedRun.origin === "manual"
      ? m.crawl_origin_manual()
      : displayedRun.origin === "scheduled"
        ? m.crawl_origin_scheduled()
        : m.crawl_origin_legacy()}
  </p>
  {#if isActiveCrawlRun(displayedRun)}
    <p class="text-secondary text-xs">{m.crawl_details_running()}</p>
  {/if}
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
    <Table.Root class="w-full table-fixed text-left text-sm">
      <Table.Header>
        <Table.Row>
          <Table.Head class="w-16 whitespace-normal">{m.crawl_failure_resource_type()}</Table.Head>
          <Table.Head>{m.crawl_failure_address()}</Table.Head>
          <Table.Head class="w-1/3 whitespace-normal">{m.crawl_failure_reason()}</Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {#each failures as failure (failure.id)}
          {@const href = resourceLink(failure.url)}
          <Table.Row>
            <Table.Cell class="py-3 align-top whitespace-normal"
              >{failure.kind === "page" ? m.page() : m.crawl_failure_file()}</Table.Cell
            >
            <Table.Cell class="py-3 align-top break-all whitespace-normal">
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
            </Table.Cell>
            <Table.Cell class="py-3 align-top break-words whitespace-normal"
              >{crawlFailureReasonLabel(failure.reason)}</Table.Cell
            >
          </Table.Row>
        {/each}
      </Table.Body>
    </Table.Root>
  {:else if !loading && !loadFailed}
    <p class="text-secondary py-4 text-sm">
      {detailsAvailable ? m.crawl_failures_empty() : m.crawl_failures_unavailable()}
    </p>
  {/if}
</div>

{#if loading}
  <p role="status" class="text-secondary text-sm">
    {failures.length ? m.loading_more() : m.loading()}
  </p>
{/if}
{#if loadFailed}
  <CrawlLoadError
    message={m.crawl_failures_load_failed()}
    {loading}
    onretry={() => loadFailures(retryCursor)}
  />
{/if}
{#if nextCursor && !loadFailed}
  <div class="flex justify-start">
    <Button variant="outline" disabled={loading} onclick={() => loadFailures(nextCursor)}>
      {m.crawl_failures_load_more({ current: failures.length, total })}
    </Button>
  </div>
{/if}
