<script lang="ts">
  import type { CrawlRun, CrawlResourceFailure, Eneo } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import { RefreshCw } from "lucide-svelte";
  import { cn } from "$lib/utils";
  import CrawlLoadError from "./CrawlLoadError.svelte";
  import CrawlRunCounts from "./CrawlRunCounts.svelte";
  import CrawlRunStatus from "./CrawlRunStatus.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import {
    crawlFailureReasonLabel,
    crawlFailureReasonHelp,
    crawlRunFailureMessage,
    isActiveCrawlRun
  } from "$lib/features/knowledge/crawlRunState";

  const eneo = getEneo();
  let {
    run,
    open = false,
    onrefresh,
    onrunupdate,
    fetchFailures = eneo.websites.crawlRuns.failures,
    initialKind = null
  }: {
    run: CrawlRun;
    open?: boolean;
    onrefresh?: () => void | Promise<void>;
    onrunupdate?: (run: CrawlRun) => void;
    fetchFailures?: Eneo["websites"]["crawlRuns"]["failures"];
    initialKind?: CrawlResourceFailure["kind"] | null;
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
  let viewedInitialKind: CrawlResourceFailure["kind"] | null = null;
  let kind = $state<CrawlResourceFailure["kind"] | null>(null);
  const filters = $derived([
    { kind: null, label: m.crawl_failures_filter_all() },
    { kind: "page" as const, label: m.crawl_counts_pages() },
    { kind: "file" as const, label: m.crawl_counts_files() }
  ]);
  const displayedRun = $derived(loadedRun ?? run);
  const summary = $derived(Object.entries(displayedRun.failure_summary ?? {}));

  async function loadFailures(cursor: string | null = null) {
    const request = ++generation;
    loading = true;
    retryCursor = cursor;
    try {
      const result = await fetchFailures({
        id: runId,
        limit: 100,
        cursor,
        ...(kind ? { kind } : {})
      });
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
    const currentInitialKind = initialKind;
    if (open && currentRun.id) {
      untrack(() => {
        // onrunupdate passes this exact proxy back through run. Keep its identity:
        // cloning it would turn snapshot adoption into another fetch/adopt cycle.
        if (currentRun === loadedRun) return;
        loadedRun = null;
        if (viewedRunId !== currentRun.id || viewedInitialKind !== currentInitialKind) {
          kind = currentInitialKind;
          failures = [];
          total = 0;
          nextCursor = null;
          detailsAvailable = true;
          loadFailed = false;
        }
        viewedRunId = currentRun.id;
        viewedInitialKind = currentInitialKind;
        void loadFailures();
      });
    } else {
      viewedRunId = null;
    }
    return () => {
      generation += 1;
    };
  });

  function selectKind(selected: CrawlResourceFailure["kind"] | null) {
    if (selected === kind) return;
    kind = selected;
    failures = [];
    total = 0;
    nextCursor = null;
    loadFailed = false;
    void loadFailures();
  }

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

<div class="min-h-0 overflow-y-auto">
  <div class="flex flex-col gap-3">
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
      <div class="max-w-sm"><CrawlRunCounts run={displayedRun} onshowFailures={selectKind} /></div>
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
    </div>

    <div class="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
      <h3 class="text-sm font-semibold">{m.crawl_failed_addresses()}</h3>
      <div class="flex gap-1" role="group" aria-label={m.crawl_failure_resource_type()}>
        {#each filters as filter (filter.label)}
          <Button
            variant={kind === filter.kind ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={kind === filter.kind}
            onclick={() => selectKind(filter.kind)}>{filter.label}</Button
          >
        {/each}
      </div>
    </div>

    <div class="min-h-0 overflow-auto" aria-busy={loading}>
      {#if summary.length > 0}
        <details class="mb-3 text-sm">
          <summary
            class="cursor-pointer rounded-sm py-1 font-medium focus-visible:outline-2 focus-visible:outline-offset-2"
            >{m.crawl_failure_help_title()}</summary
          >
          <ul class="mt-2 space-y-3">
            {#each summary as [reason, count] (reason)}
              {@const help = crawlFailureReasonHelp(reason)}
              <li>
                <p class="font-medium">{crawlFailureReasonLabel(reason)} · {count}</p>
                {#if help}<p class="text-secondary mt-0.5 max-w-prose">{help}</p>{/if}
              </li>
            {/each}
          </ul>
        </details>
      {/if}
      {#if failures.length > 0}
        <ul aria-label={m.crawl_failed_addresses()} class="divide-y text-sm">
          {#each failures as failure (failure.id)}
            {@const href = resourceLink(failure.url)}
            <li class="grid gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_12rem] sm:gap-5">
              <div class="min-w-0">
                <p class="text-secondary mb-1 text-xs">
                  {failure.kind === "page" ? m.page() : m.crawl_failure_file()}
                </p>
                {#if href}
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- validated external HTTP(S) address -->
                  <a
                    {href}
                    target="_blank"
                    rel="noreferrer"
                    class="text-accent-stronger break-all underline underline-offset-2"
                    >{failure.url}</a
                  >
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                {:else}
                  <span class="break-all">{failure.url}</span>
                {/if}
              </div>
              <p class="text-negative-stronger break-words sm:pt-5">
                {crawlFailureReasonLabel(failure.reason)}
              </p>
            </li>
          {/each}
        </ul>
      {:else if !loading && !loadFailed}
        <p class="text-secondary py-4 text-sm">
          {detailsAvailable
            ? kind
              ? m.crawl_failures_filter_empty()
              : m.crawl_failures_empty()
            : m.crawl_failures_unavailable()}
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
  </div>
</div>
