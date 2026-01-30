<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconAssistants } from "@intric/icons/assistants";
  import { IconSession } from "@intric/icons/session";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Page, Settings } from "$lib/components/layout";
  import { Input } from "@intric/ui";
  import { CalendarDate } from "@internationalized/date";
  import { getIntric } from "$lib/core/Intric";
  import type { AnalyticsAggregatedData } from "@intric/intric-js";

  import InteractiveGraph from "./InteractiveGraph.svelte";
  import TenantAssistantTable from "./TenantAssistantTable.svelte";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { onMount } from "svelte";

  // Use $props() for Svelte 5 runes mode
  let { data } = $props();

  const intric = getIntric();
  let selectedTab = writable<string>();

  // Date range state
  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getUTCDate());
  let dateRange = $state({
    start: today.subtract({ days: 30 }),
    end: today
  });

  // Analytics data state
  let analyticsData: AnalyticsAggregatedData | null = $state(null);
  let isLoading = $state(true);
  let mounted = $state(false);

  // Cache for previously fetched date ranges
  const analyticsCache = new Map<string, { data: AnalyticsAggregatedData; timeframe: { start: string; end: string } }>();
  const MAX_CACHE_ENTRIES = 12;

  // Debounce timer for date range changes
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  const DEBOUNCE_DELAY = 300; // ms

  // In-flight request tracking to prevent race conditions
  let currentFetchId = 0;

  // Derived: compute earliest data date - memoized to avoid iterating on every render
  let earliestDataDate = $derived.by(() => {
    if (!analyticsData) return null;

    let earliest: string | null = null;
    for (const session of analyticsData.sessions) {
      if (session.created_at) {
        const date = session.created_at.split("T")[0];
        if (!earliest || date < earliest) earliest = date;
      }
    }
    for (const question of analyticsData.questions) {
      if (question.created_at) {
        const date = question.created_at.split("T")[0];
        if (!earliest || date < earliest) earliest = date;
      }
    }
    return earliest;
  });

  const sumCounts = (rows: { count: number }[]) => {
    let total = 0;
    for (let i = 0; i < rows.length; i++) {
      total += rows[i].count;
    }
    return total;
  };

  let assistantTotal = $derived.by(() =>
    analyticsData ? sumCounts(analyticsData.assistants) : 0
  );
  let sessionTotal = $derived.by(() =>
    analyticsData ? sumCounts(analyticsData.sessions) : 0
  );
  let questionTotal = $derived.by(() =>
    analyticsData ? sumCounts(analyticsData.questions) : 0
  );

  // Derived: check if data range is partial - uses memoized earliestDataDate
  let partialDataInfo = $derived.by(() => {
    if (!earliestDataDate || !dateRange.start) return null;

    const requestedStart = dateRange.start.toString();
    if (earliestDataDate <= requestedStart) return null;

    // Calculate days
    const endTime = new Date(dateRange.end.toString()).getTime();
    const requestedDays = Math.ceil(
      (endTime - new Date(requestedStart).getTime()) / (1000 * 60 * 60 * 24)
    );
    const actualDays = Math.ceil(
      (endTime - new Date(earliestDataDate).getTime()) / (1000 * 60 * 60 * 24)
    ) + 1;

    return {
      actualStart: earliestDataDate,
      requestedDays,
      actualDays
    };
  });

  // Timeframe for the chart (needs full ISO datetime for parseAbsolute)
  let timeframe = $state({
    start: `${today.subtract({ days: 30 }).toString()}T00:00:00+01:00`,
    end: `${today.add({ days: 1 }).toString()}T00:00:00+01:00`
  });

  // Preset options
  const presets = [
    { label: "7d", days: 7 },
    { label: "30d", days: 30 },
    { label: "90d", days: 90 }
  ];

  // Track initial date range to avoid duplicate fetch on mount
  const initialStart = today.subtract({ days: 30 }).toString();
  const initialEnd = today.toString();
  let lastFetchedRange = $state({ start: initialStart, end: initialEnd });

  // Derived: compute active preset once per dateRange change instead of per-button render
  let activePresetDays = $derived.by(() => {
    if (!dateRange.start || !dateRange.end) return null;
    if (dateRange.end.compare(today) !== 0) return null;

    for (const preset of presets) {
      const expectedStart = today.subtract({ days: preset.days });
      if (dateRange.start.compare(expectedStart) === 0) {
        return preset.days;
      }
    }
    return null;
  });

  function setPreset(days: number) {
    dateRange = {
      start: today.subtract({ days }),
      end: today
    };
  }

  // Generate cache key from date range
  function getCacheKey(start: string, end: string): string {
    return `${start}|${end}`;
  }

  function setCache(
    key: string,
    value: { data: AnalyticsAggregatedData; timeframe: { start: string; end: string } }
  ) {
    if (analyticsCache.has(key)) {
      analyticsCache.delete(key);
    }
    analyticsCache.set(key, value);
    if (analyticsCache.size > MAX_CACHE_ENTRIES) {
      const oldestKey = analyticsCache.keys().next().value;
      if (oldestKey) {
        analyticsCache.delete(oldestKey);
      }
    }
  }

  async function fetchData(range: { start: CalendarDate; end: CalendarDate }) {
    const rangeKey = { start: range.start.toString(), end: range.end.toString() };

    // Skip if this is the same range we just fetched
    if (rangeKey.start === lastFetchedRange.start && rangeKey.end === lastFetchedRange.end) {
      return;
    }

    const cacheKey = getCacheKey(rangeKey.start, rangeKey.end);

    // Check cache first
    const cached = analyticsCache.get(cacheKey);
    if (cached) {
      setCache(cacheKey, cached);
      analyticsData = cached.data;
      timeframe = cached.timeframe;
      lastFetchedRange = rangeKey;
      isLoading = false;
      return;
    }

    isLoading = true;
    lastFetchedRange = rangeKey;

    // Track this fetch to handle race conditions
    const fetchId = ++currentFetchId;

    try {
      const tf = {
        start: range.start.toString(),
        // Add one day so the end day includes the whole day
        end: range.end.add({ days: 1 }).toString()
      };
      // Convert date strings to full ISO datetime for parseAbsolute compatibility
      const newTimeframe = {
        start: `${tf.start}T00:00:00+01:00`,
        end: `${tf.end}T00:00:00+01:00`
      };

      const result = await intric.analytics.getAggregated(tf);

      // Only update if this is still the latest request
      if (fetchId === currentFetchId) {
        timeframe = newTimeframe;
        analyticsData = result;

        // Store in cache
        setCache(cacheKey, { data: result, timeframe: newTimeframe });
      }
    } catch (error) {
      console.error("Failed to fetch analytics data:", error);
      // Keep existing data on error, just stop loading
    } finally {
      // Only update loading state if this is still the latest request
      if (fetchId === currentFetchId) {
        isLoading = false;
      }
    }
  }

  // Debounced fetch function
  function debouncedFetchData(range: { start: CalendarDate; end: CalendarDate }) {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }

    const rangeKey = { start: range.start.toString(), end: range.end.toString() };
    const cacheKey = getCacheKey(rangeKey.start, rangeKey.end);

    // If data is cached, fetch immediately (no need to debounce)
    if (analyticsCache.has(cacheKey)) {
      fetchData(range);
      return;
    }

    // Otherwise debounce to prevent API spam
    debounceTimer = setTimeout(() => {
      fetchData(range);
    }, DEBOUNCE_DELAY);
  }

  // Initial load from SSR data
  onMount(() => {
    // Handle async initialization without returning cleanup from async function
    (async () => {
      const initialData = await data.data;
      analyticsData = initialData;

      // Cache the initial SSR data
      const cacheKey = getCacheKey(initialStart, initialEnd);
      setCache(cacheKey, {
        data: initialData,
        timeframe: {
          start: `${initialStart}T00:00:00+01:00`,
          end: `${today.add({ days: 1 }).toString()}T00:00:00+01:00`
        }
      });

      isLoading = false;
      mounted = true;
    })();

    // Cleanup debounce timer on unmount
    return () => {
      if (debounceTimer) {
        clearTimeout(debounceTimer);
      }
    };
  });

  // Reactive update when date range changes
  $effect(() => {
    if (mounted && dateRange.start && dateRange.end) {
      debouncedFetchData(dateRange);
    }
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.insights()}</title>
</svelte:head>

<Page.Root tabController={selectedTab}>
  <Page.Header>
    <Page.Title title={m.insights()}></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="overview">{m.usage()}</Page.TabTrigger>
      <Page.TabTrigger tab="assistants">{m.assistants()}</Page.TabTrigger>
    </Page.Tabbar>
  </Page.Header>
  <Page.Main>
    <Page.Tab id="overview">
      {#if $selectedTab === "overview"}
        <Settings.Page>
          <Settings.Group title={m.statistics()}>
            <Settings.Row
              fullWidth
              title={m.assistant_usage()}
              description={m.assistant_usage_description()}
            >
              <!-- Date Range Picker Toolbar -->
              <div slot="toolbar" class="flex items-center gap-4">
                <Input.DateRange bind:value={dateRange} />
                <!-- Quick preset chips -->
                <div class="flex gap-1.5">
                  {#each presets as preset}
                    <button
                      class="px-2.5 py-1 text-xs rounded-full border transition-all duration-150
                             {activePresetDays === preset.days
                        ? 'bg-accent-dimmer border-accent-default text-accent-default font-medium'
                        : 'border-default text-secondary hover:bg-hover-dimmer hover:border-border-stronger'}"
                      onclick={() => setPreset(preset.days)}
                    >
                      {preset.label}
                    </button>
                  {/each}
                </div>
              </div>

              <div class="h-[600px]">
                <div
                  class="relative border-default flex h-full w-full items-stretch overflow-clip rounded-lg border shadow-sm
                         hover:border-border-stronger hover:shadow transition-all duration-200"
                >
                  {#if isLoading || !analyticsData}
                    <!-- Skeleton loading state -->
                    <div class="flex h-full w-full">
                      <!-- Chart skeleton -->
                      <div class="flex-1 p-6">
                        <div class="h-full flex flex-col gap-4">
                          <!-- Chart area skeleton -->
                          <div class="flex-1 bg-secondary/30 rounded-lg animate-pulse"></div>
                          <!-- X-axis labels skeleton -->
                          <div class="flex justify-between px-4">
                            {#each Array(7) as _}
                              <div class="h-3 w-12 bg-secondary/30 rounded animate-pulse"></div>
                            {/each}
                          </div>
                        </div>
                      </div>
                      <!-- Stat cards skeleton -->
                      <div class="flex w-64 -mr-px flex-shrink-0 flex-col divide-y divide-[var(--border-dimmer)] border-l border-default rounded-r-lg overflow-hidden">
                        {#each Array(3) as _, i}
                          <div class="flex flex-1 flex-col justify-between px-5 py-6 bg-white">
                            <div class="flex items-center gap-2">
                              <div class="h-4 w-4 bg-secondary/30 rounded animate-pulse"></div>
                              <div class="h-3 w-24 bg-secondary/30 rounded animate-pulse" style="animation-delay: {i * 100}ms"></div>
                            </div>
                            <div class="self-end h-11 w-20 bg-secondary/30 rounded animate-pulse" style="animation-delay: {i * 100 + 50}ms"></div>
                          </div>
                        {/each}
                      </div>
                    </div>
                  {:else}
                    <InteractiveGraph data={analyticsData} {timeframe} {partialDataInfo}></InteractiveGraph>

                    <!-- Stat Cards - WCAG AA + Blue Accents -->
                    <div class="flex w-64 -mr-px flex-shrink-0 flex-col divide-y divide-[var(--border-dimmer)] border-l border-default rounded-r-lg overflow-hidden">
                      <!-- Assistants Created -->
                      <div class="stat-card group flex flex-1 flex-col justify-between px-5 py-6 transition-all duration-200 ease-out bg-white hover:bg-[var(--accent-dimmer)] border-l-[3px] border-l-transparent hover:border-l-[var(--accent-default)]" style="--delay: 50ms">
                        <div class="text-secondary flex items-center gap-2 transition-colors duration-200 group-hover:text-[var(--accent-stronger)]">
                          <IconAssistants class="h-4 w-4 opacity-70 transition-opacity duration-200 group-hover:opacity-100" />
                          <span class="text-[11px] font-medium uppercase tracking-wide">{m.assistants_created()}</span>
                        </div>
                        <span class="stat-number text-primary self-end text-[2.75rem] font-normal tabular-nums tracking-tight leading-none transition-all duration-200 group-hover:text-[var(--accent-default)]" style="--delay: 50ms">
                          {assistantTotal.toLocaleString("sv-SE")}
                        </span>
                      </div>

                      <!-- Conversations Started -->
                      <div class="stat-card group flex flex-1 flex-col justify-between px-5 py-6 transition-all duration-200 ease-out bg-white hover:bg-[var(--accent-dimmer)] border-l-[3px] border-l-transparent hover:border-l-[var(--accent-default)]" style="--delay: 180ms">
                        <div class="text-secondary flex items-center gap-2 transition-colors duration-200 group-hover:text-[var(--accent-stronger)]">
                          <IconSession class="h-4 w-4 opacity-70 transition-opacity duration-200 group-hover:opacity-100" />
                          <span class="text-[11px] font-medium uppercase tracking-wide">{m.conversations_started()}</span>
                        </div>
                        <span class="stat-number text-primary self-end text-[2.75rem] font-normal tabular-nums tracking-tight leading-none transition-all duration-200 group-hover:text-[var(--accent-default)]" style="--delay: 180ms">
                          {sessionTotal.toLocaleString("sv-SE")}
                        </span>
                      </div>

                      <!-- Questions Asked -->
                      <div class="stat-card group flex flex-1 flex-col justify-between px-5 py-6 transition-all duration-200 ease-out bg-white hover:bg-[var(--accent-dimmer)] border-l-[3px] border-l-transparent hover:border-l-[var(--accent-default)]" style="--delay: 310ms">
                        <div class="text-secondary flex items-center gap-2 transition-colors duration-200 group-hover:text-[var(--accent-stronger)]">
                          <IconQuestionMark class="h-4 w-4 opacity-70 transition-opacity duration-200 group-hover:opacity-100" />
                          <span class="text-[11px] font-medium uppercase tracking-wide">{m.questions_asked()}</span>
                        </div>
                        <span class="stat-number text-primary self-end text-[2.75rem] font-normal tabular-nums tracking-tight leading-none transition-all duration-200 group-hover:text-[var(--accent-default)]" style="--delay: 310ms">
                          {questionTotal.toLocaleString("sv-SE")}
                        </span>
                      </div>
                    </div>
                  {/if}
                </div>
              </div>
            </Settings.Row>
          </Settings.Group>
        </Settings.Page>
      {/if}
    </Page.Tab>
    <Page.Tab id="assistants">
      <TenantAssistantTable assistants={data.assistants} />
    </Page.Tab>
  </Page.Main>
</Page.Root>

<style lang="postcss">
  /* Nordic Precision animations - intentional cascade */
  @keyframes fade-in-up {
    from {
      opacity: 0;
      transform: translateY(8px) scale(0.98);
    }
    to {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
  }

  @keyframes number-reveal {
    0% {
      opacity: 0;
      transform: translateY(4px);
      filter: blur(4px);
    }
    100% {
      opacity: 1;
      transform: translateY(0);
      filter: blur(0);
    }
  }

  .stat-card {
    animation: fade-in-up 0.35s ease-out both;
    animation-delay: var(--delay);
  }

  .stat-number {
    will-change: opacity, transform, filter;
    animation: number-reveal 0.45s cubic-bezier(0.16, 1, 0.3, 1) both;
    animation-delay: calc(var(--delay) + 200ms);
  }
</style>
