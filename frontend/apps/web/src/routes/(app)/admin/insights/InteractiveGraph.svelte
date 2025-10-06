<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconSession } from "@intric/icons/session";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Chart, Button } from "@intric/ui";
  import type { AnalyticsData } from "@intric/intric-js";
  import { getConfig, prepareData } from "./prepareData";
  import { m } from "$lib/paraglide/messages";

  export let data: AnalyticsData;
  export let timeframe: { start: string; end: string };

  // const preparedData = prepareData(data, timeframe);
  const datasets = prepareData(data, timeframe);

  let dataset = datasets.byDate; // by date, weekday, hour
  let filter: "sessions" | "questions" = "sessions"; // sessions or question

  $: config = getConfig(dataset, filter);
</script>

<div class="flex w-[calc(100%_-_240px)] flex-col gap-4">
  <div class="border-default flex gap-2 border-b p-2">
    <Button
      displayActiveState
      data-state={filter === "sessions" ? "active" : "incative"}
      on:click={() => {
        filter = "sessions";
      }}
    >
      <IconSession />
      {m.new_conversations()}</Button
    >
    <Button
      displayActiveState
      data-state={filter === "questions" ? "active" : "incative"}
      on:click={() => {
        filter = "questions";
      }}
    >
      <IconQuestionMark />
      {m.new_questions()}</Button
    >
    <div class="flex-grow"></div>
    <Button
      displayActiveState
      data-state={dataset === datasets.byDate ? "active" : "incative"}
      on:click={() => {
        dataset = datasets.byDate;
      }}>{m.by_date()}</Button
    >
    <Button
      displayActiveState
      data-state={dataset === datasets.byWeekday ? "active" : "incative"}
      on:click={() => {
        dataset = datasets.byWeekday;
      }}>{m.by_weekday()}</Button
    >
    <Button
      displayActiveState
      data-state={dataset === datasets.byHour ? "active" : "incative"}
      on:click={() => {
        dataset = datasets.byHour;
      }}>{m.by_hour()}</Button
    >
  </div>
  <div class="h-full w-full px-6 pt-2 pb-4">
    <Chart.Root {config}></Chart.Root>
  </div>
</div>
