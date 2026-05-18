<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import type { TokenUsageSummary } from "@intric/intric-js";
  import TokenOverviewBar from "./TokenOverviewBar.svelte";
  import TokenOverviewTable from "./TokenOverviewTable.svelte";
  import UserTokenSummary from "../users/UserTokenSummary.svelte";
  import { CalendarDate, type DateValue } from "@internationalized/date";
  import { getIntric } from "$lib/core/Intric";
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import { formatPercent } from "$lib/core/formatting/formatPercent";

  type Props = {
    tokenStats: TokenUsageSummary;
  };

  type UsageSourceFilter = "" | "chat" | "app_run" | "crawler_embedding";

  const { tokenStats }: Props = $props();
  let detailedStats = $state(untrack(() => tokenStats));
  let sourceFilter = $state<UsageSourceFilter>("");
  const costCoverageRatio = $derived(detailedStats.cost_coverage_ratio);

  const intric = getIntric();

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
  let dateRange = $state({
    start: today.subtract({ days: 30 }),
    end: today
  });

  const sourceOptions: { value: UsageSourceFilter; label: string }[] = [
    { value: "", label: m.token_usage_source_filter_all() },
    { value: "chat", label: m.token_usage_source_chat() },
    { value: "app_run", label: m.token_usage_source_app_run() },
    { value: "crawler_embedding", label: m.token_usage_source_crawler_embedding() }
  ];

  async function update(
    timeframe: { start: CalendarDate; end: CalendarDate },
    sourceType: UsageSourceFilter = sourceFilter
  ) {
    detailedStats = await intric.usage.tokens.getSummary({
      startDate: timeframe.start.toString(),
      // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
      endDate: timeframe.end.add({ days: 1 }).toString(),
      sourceType: sourceType || undefined
    });
  }

  function handleDateChange(range: { start: DateValue; end: DateValue }) {
    dateRange = range as { start: CalendarDate; end: CalendarDate };
    update(dateRange);
  }

  function setSourceFilter(next: UsageSourceFilter) {
    if (next === sourceFilter) return;
    sourceFilter = next;
    update(dateRange, next);
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
      <div class="mb-4 flex flex-wrap gap-2">
        {#each sourceOptions as option (option.value)}
          <button
            type="button"
            aria-pressed={sourceFilter === option.value}
            class={[
              "rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors",
              sourceFilter === option.value
                ? "border-accent-default bg-accent-default/10 text-accent-default"
                : "border-border text-muted-foreground hover:text-foreground"
            ]}
            onclick={() => setSourceFilter(option.value)}
          >
            {option.label}
          </button>
        {/each}
      </div>
      {#if detailedStats.cost_trackable_token_usage > 0 && typeof costCoverageRatio === "number" && costCoverageRatio < 1}
        <p class="text-muted-foreground mb-4 text-sm">
          {m.token_usage_cost_coverage({
            ratio: formatPercent(costCoverageRatio),
            tokens: formatNumber(detailedStats.cost_trackable_token_usage)
          })}
        </p>
      {/if}
      <TokenOverviewTable tokenStats={detailedStats}></TokenOverviewTable>
    </Settings.Row>
  </Settings.Group>
  <UserTokenSummary />
</Settings.Page>
