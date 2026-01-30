<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconSession } from "@intric/icons/session";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Chart, Button } from "@intric/ui";
  import { Info } from "lucide-svelte";
  import type { AnalyticsAggregatedData } from "@intric/intric-js";
  import { getConfig, prepareData } from "./prepareData";
  import { m } from "$lib/paraglide/messages";

  // Svelte 5 runes: use $props() instead of export let
  let {
    data,
    timeframe,
    partialDataInfo = null
  }: {
    data: AnalyticsAggregatedData;
    timeframe: { start: string; end: string };
    partialDataInfo: { actualStart: string; requestedDays: number; actualDays: number } | null;
  } = $props();

  // Memoize prepareData - only recomputes when data or timeframe changes
  let datasets = $derived.by(() => prepareData(data, timeframe));

  // Track which dataset view is selected: "byDate" | "byWeekday" | "byHour"
  let datasetKey = $state<"byDate" | "byWeekday" | "byHour">("byDate");
  let filter = $state<"sessions" | "questions">("sessions");

  // Derive the current dataset from the key
  let dataset = $derived(datasets[datasetKey]);

  // Memoize config - only recomputes when dataset or filter changes
  let config = $derived.by(() => getConfig(dataset, filter));
</script>

<div class="flex w-[calc(100%_-_256px)] flex-col">
  <!-- Toggle Toolbar -->
  <div class="border-default flex items-center justify-between gap-4 border-b px-5 py-3.5">
    <!-- Metric Toggles (Left) - With underline indicator -->
    <div class="flex items-center gap-1">
      <button
        class="group relative flex items-center gap-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors duration-200
               {filter === 'sessions' ? 'text-[var(--accent-stronger)]' : 'text-secondary hover:text-primary'}"
        onclick={() => { filter = "sessions"; }}
      >
        <IconSession class="h-4 w-4 transition-opacity duration-200
                           {filter === 'sessions' ? 'opacity-100' : 'opacity-60 group-hover:opacity-100'}" />
        <span>{m.new_conversations()}</span>
        <span class="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--accent-default)] transition-transform duration-200 origin-left
                     {filter === 'sessions' ? 'scale-x-100' : 'scale-x-0'}"></span>
      </button>
      <button
        class="group relative flex items-center gap-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors duration-200
               {filter === 'questions' ? 'text-[var(--accent-stronger)]' : 'text-secondary hover:text-primary'}"
        onclick={() => { filter = "questions"; }}
      >
        <IconQuestionMark class="h-4 w-4 transition-opacity duration-200
                                 {filter === 'questions' ? 'opacity-100' : 'opacity-60 group-hover:opacity-100'}" />
        <span>{m.new_questions()}</span>
        <span class="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--accent-default)] transition-transform duration-200 origin-left
                     {filter === 'questions' ? 'scale-x-100' : 'scale-x-0'}"></span>
      </button>
    </div>

    <!-- Grouping Toggles (Right) - Segmented Control with abbreviated labels -->
    <div class="flex items-center rounded-lg border border-[var(--border-dimmer)] bg-[var(--background-secondary)] p-1">
      <button
        class="rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-all duration-200
               {datasetKey === 'byDate'
                 ? 'bg-white text-primary shadow-[0_1px_4px_rgba(0,0,0,0.1)]'
                 : 'text-secondary hover:text-primary hover:bg-white/50'}"
        onclick={() => { datasetKey = 'byDate'; }}
      >Datum</button>
      <button
        class="rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-all duration-200
               {datasetKey === 'byWeekday'
                 ? 'bg-white text-primary shadow-[0_1px_4px_rgba(0,0,0,0.1)]'
                 : 'text-secondary hover:text-primary hover:bg-white/50'}"
        onclick={() => { datasetKey = 'byWeekday'; }}
      >Veckodag</button>
      <button
        class="rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-all duration-200
               {datasetKey === 'byHour'
                 ? 'bg-white text-primary shadow-[0_1px_4px_rgba(0,0,0,0.1)]'
                 : 'text-secondary hover:text-primary hover:bg-white/50'}"
        onclick={() => { datasetKey = 'byHour'; }}
      >Timme</button>
    </div>
  </div>

  <!-- Chart Area -->
  <div class="relative h-full w-full px-8 pt-6 pb-5">
    <Chart.Root {config}></Chart.Root>

    <!-- Partial data info - bottom-left corner, subtle -->
    {#if partialDataInfo}
      <div class="absolute bottom-6 left-10 flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
        <Info class="h-3 w-3 opacity-40" />
        <span>{partialDataInfo.actualStart} ({partialDataInfo.actualDays}/{partialDataInfo.requestedDays}d)</span>
      </div>
    {/if}
  </div>
</div>
