<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconAssistants } from "@intric/icons/assistants";
  import { IconSession } from "@intric/icons/session";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Page, Settings } from "$lib/components/layout";
  import { Input, Button } from "@intric/ui";
  import { CalendarDate } from "@internationalized/date";
  import { getIntric } from "$lib/core/Intric";
  import type { AnalyticsAggregatedData } from "@intric/intric-js";
  import { ArrowUp, ArrowDown, GitCompare, RefreshCw, Clock, Cpu, ExternalLink } from "lucide-svelte";
  import { formatNumber } from "$lib/core/formatting/formatNumber";

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

  // Period comparison state
  let showComparison = $state(false);
  let comparisonData: AnalyticsAggregatedData | null = $state(null);
  let isLoadingComparison = $state(false);
  const comparisonCache = new Map<string, AnalyticsAggregatedData>();

  // Data freshness tracking
  let lastUpdated = $state<Date | null>(null);

  // Token usage state
  type TokenUsageSummary = {
    total_token_usage: number;
    total_input_token_usage: number;
    total_output_token_usage: number;
  };
  let tokenUsage: TokenUsageSummary | null = $state(null);
  let isLoadingTokens = $state(false);
  let tokenError = $state(false);

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

  // Comparison totals
  let comparisonAssistantTotal = $derived.by(() =>
    comparisonData ? sumCounts(comparisonData.assistants) : 0
  );
  let comparisonSessionTotal = $derived.by(() =>
    comparisonData ? sumCounts(comparisonData.sessions) : 0
  );
  let comparisonQuestionTotal = $derived.by(() =>
    comparisonData ? sumCounts(comparisonData.questions) : 0
  );

  // Calculate trend percentage - caps extreme values for cleaner display
  function calculateTrend(current: number, previous: number): { value: string; direction: 'up' | 'down' | 'neutral'; tooltip: string } | null {
    if (current === 0 && previous === 0) return null; // No change to report
    if (previous === 0) return { value: m.compare_new_activity(), direction: 'neutral', tooltip: m.compare_new_activity_tooltip() }; // New activity, no baseline
    const pct = Math.round(((current - previous) / previous) * 100);
    if (pct === 0) return null;
    const absPct = Math.abs(pct);
    // Cap display at 999% for cleaner UI, show actual in tooltip
    const displayValue = absPct > 999 ? '>999%' : `${absPct}%`;
    const direction = pct > 0 ? 'up' : 'down';
    const tooltip = direction === 'up'
      ? m.compare_increase_tooltip({ percent: absPct.toLocaleString() })
      : m.compare_decrease_tooltip({ percent: absPct.toLocaleString() });
    return {
      value: displayValue,
      direction,
      tooltip
    };
  }

  // Derived trends
  let assistantTrend = $derived.by(() =>
    showComparison && comparisonData ? calculateTrend(assistantTotal, comparisonAssistantTotal) : null
  );
  let sessionTrend = $derived.by(() =>
    showComparison && comparisonData ? calculateTrend(sessionTotal, comparisonSessionTotal) : null
  );
  let questionTrend = $derived.by(() =>
    showComparison && comparisonData ? calculateTrend(questionTotal, comparisonQuestionTotal) : null
  );

  // Formatted date range for header
  let formattedDateRange = $derived.by(() => {
    if (!dateRange.start || !dateRange.end) return "";
    const days = dateRange.end.toDate("Europe/Stockholm").getTime() - dateRange.start.toDate("Europe/Stockholm").getTime();
    const dayCount = Math.round(days / (1000 * 60 * 60 * 24));
    const startStr = `${dateRange.start.day.toString().padStart(2, '0')}/${dateRange.start.month.toString().padStart(2, '0')}`;
    const endStr = `${dateRange.end.day.toString().padStart(2, '0')}/${dateRange.end.month.toString().padStart(2, '0')}`;
    return `${dayCount} dagar: ${startStr}–${endStr}`;
  });

  // Formatted last updated time
  let formattedLastUpdated = $derived.by(() => {
    if (!lastUpdated) return "";
    return lastUpdated.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' });
  });

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
        lastUpdated = new Date();

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

  // Fetch comparison data when comparison is toggled on
  async function fetchComparisonData() {
    if (!dateRange.start || !dateRange.end) return;

    // Calculate previous period duration
    const startMs = dateRange.start.toDate("Europe/Stockholm").getTime();
    const endMs = dateRange.end.toDate("Europe/Stockholm").getTime();
    const durationMs = endMs - startMs;

    // Previous period = [start - duration, start) exclusive end
    const previousEnd = dateRange.start;
    const previousStartMs = startMs - durationMs;
    const previousStartDate = new Date(previousStartMs);
    const previousStart = new CalendarDate(
      previousStartDate.getFullYear(),
      previousStartDate.getMonth() + 1,
      previousStartDate.getDate()
    );

    const cacheKey = `${previousStart.toString()}|${previousEnd.toString()}`;

    // Check cache first
    const cached = comparisonCache.get(cacheKey);
    if (cached) {
      comparisonData = cached;
      return;
    }

    isLoadingComparison = true;

    try {
      const tf = {
        start: previousStart.toString(),
        end: previousEnd.toString()
      };
      const result = await intric.analytics.getAggregated(tf);
      comparisonData = result;
      comparisonCache.set(cacheKey, result);
    } catch (error) {
      console.error("Failed to fetch comparison data:", error);
      comparisonData = null;
    } finally {
      isLoadingComparison = false;
    }
  }

  // Reactive fetch comparison when toggled on
  $effect(() => {
    if (showComparison && mounted && !comparisonData && !isLoadingComparison) {
      fetchComparisonData();
    }
  });

  // Clear comparison data when date range changes
  $effect(() => {
    if (dateRange.start && dateRange.end) {
      comparisonData = null;
      if (showComparison) {
        fetchComparisonData();
      }
    }
  });

  // Fetch token usage data
  async function fetchTokenUsage() {
    if (!dateRange.start || !dateRange.end) return;

    isLoadingTokens = true;
    tokenError = false;

    try {
      const result = await intric.usage.tokens.getSummary({
        startDate: dateRange.start.toString(),
        endDate: dateRange.end.add({ days: 1 }).toString()
      });
      tokenUsage = result;
    } catch (error) {
      console.error("Failed to fetch token usage:", error);
      tokenError = true;
      tokenUsage = null;
    } finally {
      isLoadingTokens = false;
    }
  }

  // Fetch token usage when date range changes
  $effect(() => {
    if (mounted && dateRange.start && dateRange.end) {
      fetchTokenUsage();
    }
  });

  // Derived: tokens per conversation
  let tokensPerConversation = $derived.by(() => {
    if (!tokenUsage || sessionTotal === 0) return null;
    return Math.round(tokenUsage.total_token_usage / sessionTotal);
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
                <!-- Comparison toggle -->
                <button
                  class="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border transition-all duration-150
                         {showComparison
                    ? 'bg-[var(--accent-dimmer)] border-[var(--accent-default)] text-[var(--accent-stronger)] font-medium'
                    : 'border-[var(--border-default)] text-[var(--text-secondary)] hover:bg-[var(--background-hover-dimmer)] hover:border-[var(--border-stronger)]'}"
                  onclick={() => { showComparison = !showComparison; }}
                  aria-pressed={showComparison}
                >
                  <GitCompare class="h-3.5 w-3.5" />
                  <span>{m.compare()}</span>
                </button>
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
                      <!-- Stat cards skeleton - Nordic style -->
                      <div class="flex w-72 -mr-px flex-shrink-0 flex-col border-l border-[var(--border-default)] rounded-r-xl overflow-hidden bg-[var(--background-primary)]">
                        <!-- Header skeleton -->
                        <div class="flex items-center justify-between px-5 py-3 border-b border-[var(--border-dimmer)] bg-[var(--background-secondary)]">
                          <div class="flex flex-col gap-1">
                            <div class="h-3 w-28 bg-[var(--background-hover-dimmer)] rounded animate-pulse"></div>
                            <div class="h-2 w-20 bg-[var(--background-hover-dimmer)] rounded animate-pulse" style="animation-delay: 50ms"></div>
                          </div>
                        </div>
                        {#each Array(3) as _, i}
                          <div class="flex flex-1 flex-col justify-between px-5 py-5 bg-[var(--background-primary)] {i > 0 ? 'border-t border-[var(--border-dimmer)]' : ''}">
                            <div class="flex items-center gap-2.5">
                              <!-- Icon skeleton - just a small circle, no box -->
                              <div class="h-4 w-4 bg-[var(--background-hover-dimmer)] rounded-full animate-pulse" style="animation-delay: {i * 80}ms"></div>
                              <div class="h-3 w-28 bg-[var(--background-hover-dimmer)] rounded animate-pulse" style="animation-delay: {i * 80 + 30}ms"></div>
                            </div>
                            <div class="self-end h-10 w-20 bg-[var(--background-secondary)] rounded animate-pulse mt-3" style="animation-delay: {i * 80 + 60}ms"></div>
                          </div>
                        {/each}
                      </div>
                    </div>
                  {:else}
                    <InteractiveGraph data={analyticsData} {timeframe} {partialDataInfo}></InteractiveGraph>

                    <!-- Stat Cards Panel - Nordic Precision v2 -->
                    <div class="stat-panel flex w-72 -mr-px flex-shrink-0 flex-col border-l border-[var(--border-default)] rounded-r-xl bg-[var(--background-primary)]">
                      <!-- Stats Header - Refined hierarchy -->
                      <div class="stat-card-header flex items-center justify-between px-5 py-3.5 border-b border-[var(--border-dimmer)] bg-[var(--background-secondary)]" style="--delay: 0ms">
                        <div class="flex flex-col gap-1">
                          <span class="text-[12px] font-semibold text-[var(--text-primary)] tracking-tight leading-none">{formattedDateRange}</span>
                          {#if formattedLastUpdated}
                            <span class="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] opacity-70">
                              <Clock class="h-2.5 w-2.5" />
                              <span>Uppdaterad {formattedLastUpdated}</span>
                            </span>
                          {/if}
                        </div>
                        {#if showComparison}
                          <div class="flex items-center gap-1.5 px-2 py-1 rounded-md bg-[var(--accent-dimmer)] ring-1 ring-[var(--accent-default)]/30">
                            <div class="w-1.5 h-1.5 rounded-full bg-[var(--accent-default)] animate-pulse"></div>
                            <span class="text-[9px] font-bold text-[var(--accent-stronger)] uppercase tracking-wider">{m.compare()}</span>
                          </div>
                        {/if}
                      </div>

                      <!-- Assistants Created -->
                      <div
                        class="stat-card group relative flex flex-1 flex-col px-5 py-6 transition-all duration-300 ease-out bg-[var(--background-primary)] hover:bg-[var(--background-hover-dimmer)] border-l-2 border-l-transparent hover:border-l-[var(--accent-default)]
                               {showComparison && assistantTrend ? 'cursor-help' : ''}"
                        style="--delay: 50ms"
                      >

                        <div class="relative flex items-center gap-2.5 mb-3">
                          <!-- Icon without box - elegant glyph -->
                          <IconAssistants class="h-4 w-4 shrink-0 text-[var(--text-muted)] opacity-50 group-hover:opacity-100 group-hover:text-[var(--accent-default)] transition-all duration-200" />
                          <span class="text-[11px] font-semibold tracking-[0.06em] uppercase text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors duration-200 flex-1">{m.assistants_created()}</span>
                          <!-- Reserved badge space prevents layout shift -->
                          <div class="h-5 flex items-center justify-end min-w-[52px] relative">
                            {#if showComparison && assistantTrend}
                              <!-- Tooltip on hover - theme-aware, positioned right to stay in view -->
                              <div class="stat-tooltip absolute bottom-full right-0 mb-2 px-2.5 py-1.5 rounded-md text-[11px] leading-snug shadow-lg z-[100] opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-100 delay-75 pointer-events-none bg-[var(--background-primary)] text-[var(--text-primary)] border border-[var(--border-default)] whitespace-normal" style="width: max-content; max-width: 180px;">
                                {assistantTrend.tooltip}
                              </div>
                              <div
                                class="trend-badge flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-medium tabular-nums
                                       {assistantTrend.direction === 'up' ? 'bg-[var(--accent-dimmer)] text-[var(--accent-stronger)] ring-1 ring-[var(--accent-default)]/30' : assistantTrend.direction === 'down' ? 'bg-[var(--negative-dimmer)] text-[var(--negative-stronger)] ring-1 ring-[var(--negative-default)]/30' : 'bg-[var(--background-secondary)] text-[var(--text-secondary)] ring-1 ring-[var(--border-default)]'}"
                                aria-label={assistantTrend.tooltip}
                              >
                                {#if assistantTrend.direction === 'up'}
                                  <ArrowUp class="h-2.5 w-2.5" />
                                {:else if assistantTrend.direction === 'down'}
                                  <ArrowDown class="h-2.5 w-2.5" />
                                {/if}
                                <span>{assistantTrend.value}</span>
                              </div>
                            {/if}
                          </div>
                        </div>

                        <span class="stat-number text-4xl font-semibold tabular-nums tracking-tight text-[var(--text-primary)] group-hover:text-[var(--accent-stronger)] transition-colors duration-300 text-right" style="--delay: 50ms">
                          {assistantTotal.toLocaleString("sv-SE")}
                        </span>
                      </div>

                      <!-- Conversations Started -->
                      <div
                        class="stat-card group relative flex flex-1 flex-col px-5 py-6 transition-all duration-300 ease-out bg-[var(--background-primary)] hover:bg-[var(--background-hover-dimmer)] border-l-2 border-l-transparent hover:border-l-[var(--accent-default)] border-t border-[var(--border-dimmer)]
                               {showComparison && sessionTrend ? 'cursor-help' : ''}"
                        style="--delay: 150ms"
                      >

                        <div class="relative flex items-center gap-2.5 mb-3">
                          <!-- Icon without box - elegant glyph -->
                          <IconSession class="h-4 w-4 shrink-0 text-[var(--text-muted)] opacity-50 group-hover:opacity-100 group-hover:text-[var(--accent-default)] transition-all duration-200" />
                          <span class="text-[11px] font-semibold tracking-[0.06em] uppercase text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors duration-200 flex-1">{m.conversations_started()}</span>
                          <!-- Reserved badge space prevents layout shift -->
                          <div class="h-5 flex items-center justify-end min-w-[52px] relative">
                            {#if showComparison && sessionTrend}
                              <!-- Tooltip on hover - theme-aware, positioned right to stay in view -->
                              <div class="stat-tooltip absolute bottom-full right-0 mb-2 px-2.5 py-1.5 rounded-md text-[11px] leading-snug shadow-lg z-[100] opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-100 delay-75 pointer-events-none bg-[var(--background-primary)] text-[var(--text-primary)] border border-[var(--border-default)] whitespace-normal" style="width: max-content; max-width: 180px;">
                                {sessionTrend.tooltip}
                              </div>
                              <div
                                class="trend-badge flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-medium tabular-nums
                                       {sessionTrend.direction === 'up' ? 'bg-[var(--accent-dimmer)] text-[var(--accent-stronger)] ring-1 ring-[var(--accent-default)]/30' : sessionTrend.direction === 'down' ? 'bg-[var(--negative-dimmer)] text-[var(--negative-stronger)] ring-1 ring-[var(--negative-default)]/30' : 'bg-[var(--background-secondary)] text-[var(--text-secondary)] ring-1 ring-[var(--border-default)]'}"
                                aria-label={sessionTrend.tooltip}
                              >
                                {#if sessionTrend.direction === 'up'}
                                  <ArrowUp class="h-2.5 w-2.5" />
                                {:else if sessionTrend.direction === 'down'}
                                  <ArrowDown class="h-2.5 w-2.5" />
                                {/if}
                                <span>{sessionTrend.value}</span>
                              </div>
                            {/if}
                          </div>
                        </div>

                        <span class="stat-number text-4xl font-semibold tabular-nums tracking-tight text-[var(--text-primary)] group-hover:text-[var(--accent-stronger)] transition-colors duration-300 text-right" style="--delay: 150ms">
                          {sessionTotal.toLocaleString("sv-SE")}
                        </span>
                      </div>

                      <!-- Questions Asked -->
                      <div
                        class="stat-card group relative flex flex-1 flex-col px-5 py-6 transition-all duration-300 ease-out bg-[var(--background-primary)] hover:bg-[var(--background-hover-dimmer)] border-l-2 border-l-transparent hover:border-l-[var(--accent-default)] border-t border-[var(--border-dimmer)]
                               {showComparison && questionTrend ? 'cursor-help' : ''}"
                        style="--delay: 250ms"
                      >

                        <div class="relative flex items-center gap-2.5 mb-3">
                          <!-- Icon without box - elegant glyph -->
                          <IconQuestionMark class="h-4 w-4 shrink-0 text-[var(--text-muted)] opacity-50 group-hover:opacity-100 group-hover:text-[var(--accent-default)] transition-all duration-200" />
                          <span class="text-[11px] font-semibold tracking-[0.06em] uppercase text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors duration-200 flex-1">{m.questions_asked()}</span>
                          <!-- Reserved badge space prevents layout shift -->
                          <div class="h-5 flex items-center justify-end min-w-[52px] relative">
                            {#if showComparison && questionTrend}
                              <!-- Tooltip on hover - theme-aware, positioned right to stay in view -->
                              <div class="stat-tooltip absolute bottom-full right-0 mb-2 px-2.5 py-1.5 rounded-md text-[11px] leading-snug shadow-lg z-[100] opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-100 delay-75 pointer-events-none bg-[var(--background-primary)] text-[var(--text-primary)] border border-[var(--border-default)] whitespace-normal" style="width: max-content; max-width: 180px;">
                                {questionTrend.tooltip}
                              </div>
                              <div
                                class="trend-badge flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-medium tabular-nums
                                       {questionTrend.direction === 'up' ? 'bg-[var(--accent-dimmer)] text-[var(--accent-stronger)] ring-1 ring-[var(--accent-default)]/30' : questionTrend.direction === 'down' ? 'bg-[var(--negative-dimmer)] text-[var(--negative-stronger)] ring-1 ring-[var(--negative-default)]/30' : 'bg-[var(--background-secondary)] text-[var(--text-secondary)] ring-1 ring-[var(--border-default)]'}"
                                aria-label={questionTrend.tooltip}
                              >
                                {#if questionTrend.direction === 'up'}
                                  <ArrowUp class="h-2.5 w-2.5" />
                                {:else if questionTrend.direction === 'down'}
                                  <ArrowDown class="h-2.5 w-2.5" />
                                {/if}
                                <span>{questionTrend.value}</span>
                              </div>
                            {/if}
                          </div>
                        </div>

                        <span class="stat-number text-4xl font-semibold tabular-nums tracking-tight text-[var(--text-primary)] group-hover:text-[var(--accent-stronger)] transition-colors duration-300 text-right" style="--delay: 250ms">
                          {questionTotal.toLocaleString("sv-SE")}
                        </span>
                      </div>

                      <!-- Token Usage - Clickable card linking to full usage -->
                      <a
                        href="/admin/usage?tab=tokens"
                        class="stat-card group relative flex flex-1 flex-col px-5 py-6 transition-all duration-300 ease-out bg-[var(--background-primary)] hover:bg-[var(--background-hover-dimmer)] border-l-2 border-l-transparent hover:border-l-[var(--accent-default)] border-t border-[var(--border-dimmer)] cursor-pointer no-underline"
                        style="--delay: 350ms"
                      >
                        <div class="relative flex items-center gap-2.5 mb-3">
                          <!-- Icon without box - elegant glyph -->
                          <Cpu class="h-4 w-4 shrink-0 text-[var(--text-muted)] opacity-50 group-hover:opacity-100 group-hover:text-[var(--accent-default)] transition-all duration-200" />
                          <span class="text-[11px] font-semibold tracking-[0.06em] uppercase text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors duration-200 flex-1">{m.tokens()}</span>
                          <!-- External link indicator - visible on hover -->
                          <ExternalLink class="h-3.5 w-3.5 text-[var(--text-muted)] opacity-0 group-hover:opacity-60 transition-opacity duration-200" />
                        </div>

                        {#if isLoadingTokens}
                          <div class="self-end h-10 w-16 bg-[var(--background-secondary)] rounded animate-pulse"></div>
                        {:else if tokenError}
                          <button
                            class="text-sm text-[var(--text-muted)] hover:text-[var(--accent-default)] transition-colors text-right"
                            onclick={(e) => { e.preventDefault(); fetchTokenUsage(); }}
                          >
                            {m.retry()}
                          </button>
                        {:else if tokenUsage}
                          <!-- Tooltip with breakdown - labels left, numbers right for scannability -->
                          <div class="stat-tooltip absolute bottom-full right-0 mb-2 px-3 py-2.5 rounded-md bg-[var(--background-primary)] border border-[var(--border-default)] shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-opacity duration-150 delay-75 pointer-events-none z-50">
                            <div class="flex flex-col gap-1.5 text-[11px] min-w-[130px]">
                              <!-- Input row -->
                              <div class="flex items-center justify-between gap-4">
                                <span class="text-[var(--text-muted)]">Inmatning</span>
                                <span class="font-medium tabular-nums text-[var(--text-secondary)]">
                                  {formatNumber(tokenUsage.total_input_token_usage, "compact")}
                                </span>
                              </div>
                              <!-- Output row -->
                              <div class="flex items-center justify-between gap-4">
                                <span class="text-[var(--text-muted)]">Utmatning</span>
                                <span class="font-medium tabular-nums text-[var(--text-secondary)]">
                                  {formatNumber(tokenUsage.total_output_token_usage, "compact")}
                                </span>
                              </div>
                              <!-- Tokens per conversation -->
                              {#if tokensPerConversation}
                                <div class="flex items-center justify-between gap-4 pt-1.5 mt-0.5 border-t border-[var(--border-dimmer)]">
                                  <span class="text-[var(--text-muted)]">Per konv</span>
                                  <span class="tabular-nums text-[var(--text-muted)]">
                                    ~{formatNumber(tokensPerConversation, "compact")}
                                  </span>
                                </div>
                              {/if}
                            </div>
                          </div>

                          <span class="stat-number text-4xl font-semibold tabular-nums tracking-tight text-[var(--text-primary)] group-hover:text-[var(--accent-stronger)] transition-colors duration-300 text-right" style="--delay: 350ms">
                            {formatNumber(tokenUsage.total_token_usage, "compact")}
                          </span>
                        {:else}
                          <span class="stat-number text-4xl font-semibold tabular-nums tracking-tight text-[var(--text-muted)] text-right" style="--delay: 350ms">
                            —
                          </span>
                        {/if}
                      </a>
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
  /* Nordic Precision Design System - Refined animations */

  /* Subtle fade-in with minimal movement */
  @keyframes nordic-fade-in {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  /* Number reveal - clean, no blur */
  @keyframes nordic-number-reveal {
    0% {
      opacity: 0;
      transform: translateY(4px);
    }
    100% {
      opacity: 1;
      transform: translateY(0);
    }
  }

  /* Badge appear - subtle slide from right */
  @keyframes nordic-badge-appear {
    0% {
      opacity: 0;
      transform: translateX(6px);
    }
    100% {
      opacity: 1;
      transform: translateX(0);
    }
  }

  .stat-card-header {
    animation: nordic-fade-in 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94) both;
    animation-delay: var(--delay);
  }

  .stat-card {
    animation: nordic-fade-in 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94) both;
    animation-delay: var(--delay);
  }

  .stat-number {
    will-change: opacity, transform;
    animation: nordic-number-reveal 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
    animation-delay: calc(var(--delay) + 100ms);
  }

  .trend-badge {
    animation: nordic-badge-appear 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94) both;
    animation-delay: calc(var(--delay, 0ms) + 200ms);
  }
</style>
