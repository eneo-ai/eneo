<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import type {
    CompletionModel,
    EmbeddingModel,
    TokenUsageSummary,
    TranscriptionModel
  } from "@eneo/eneo-js";
  import TokenOverviewBar from "./TokenOverviewBar.svelte";
  import TokenOverviewTable from "./TokenOverviewTable.svelte";
  import UserTokenSummary from "../users/UserTokenSummary.svelte";
  import { CalendarDate, type DateValue } from "@internationalized/date";
  import { getEneo } from "$lib/core/Eneo";
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { buildCostRateMap } from "$lib/features/ai-models/costRates";

  type ModelsList = {
    completionModels: CompletionModel[];
    embeddingModels: EmbeddingModel[];
    transcriptionModels: TranscriptionModel[];
  };

  type Props = {
    tokenStats: TokenUsageSummary;
    models: ModelsList;
  };

  const { tokenStats, models }: Props = $props();
  let detailedStats = $state(untrack(() => tokenStats));

  // Cost map is stable for the page lifetime — models change rarely. Building
  // once here avoids re-walking the list on every row render. We untrack the
  // read so $state doesn't warn that the initial value is captured (it is —
  // intentionally; reactivity for live model edits is out of scope here).
  const costRates = untrack(() => buildCostRateMap(models));

  const eneo = getEneo();

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
  let dateRange = $state({
    start: today.subtract({ days: 30 }),
    end: today
  });

  async function update(timeframe: { start: CalendarDate; end: CalendarDate }) {
    detailedStats = await eneo.usage.tokens.getSummary({
      startDate: timeframe.start.toString(),
      // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
      endDate: timeframe.end.add({ days: 1 }).toString()
    });
  }

  function handleDateChange(range: { start: DateValue; end: DateValue }) {
    dateRange = range as { start: CalendarDate; end: CalendarDate };
    update(dateRange);
  }
</script>

<Settings.Page>
  <Settings.Group title={m.overview()}>
    <TokenOverviewBar {tokenStats}></TokenOverviewBar>
  </Settings.Group>
  <Settings.Group title={m.details()}>
    <Settings.Row title={m.usage_by_model()} description={m.see_token_usage_by_model()} fullWidth>
      <div slot="toolbar">
        <Input.DateRange bind:value={dateRange} onValueCommit={handleDateChange}></Input.DateRange>
      </div>
      <TokenOverviewTable tokenStats={detailedStats} {costRates}></TokenOverviewTable>
    </Settings.Row>
  </Settings.Group>
  <UserTokenSummary {costRates} />
</Settings.Page>
