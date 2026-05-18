<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { TokenUsageSummary } from "@intric/intric-js";
  import { createRender } from "svelte-headless-table";
  import { Button, Table } from "@intric/ui";
  import ModelNameAndVendor from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  export let tokenStats: TokenUsageSummary;

  $: models = tokenStats.models.toSorted((a, b) =>
    (a.model_org ?? "").localeCompare(b.model_org ?? "")
  );

  let showAllItems = false;

  $: visibleItems = showAllItems ? models : models.slice(0, 10);

  const table = Table.createWithResource(visibleItems);

  function sourceTypeLabel(sourceType: string): string {
    switch (sourceType) {
      case "chat":
        return m.token_usage_source_chat();
      case "app_run":
        return m.token_usage_source_app_run();
      case "crawler_embedding":
        return m.token_usage_source_crawler_embedding();
      default:
        return sourceType;
    }
  }

  function sourceTypesLabel(sourceTypes: string[]): string {
    if (sourceTypes.length === 0) return "—";
    return sourceTypes.map(sourceTypeLabel).join(", ");
  }

  function formatUsdCost(value: string | null | undefined): string {
    if (!value) return "—";
    return new Intl.NumberFormat(getLocale(), {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 6
    }).format(Number(value));
  }

  function costLabel(item: TokenUsageSummary["models"][number]): string {
    if (item.total_cost_usd) return formatUsdCost(item.total_cost_usd);
    if (item.cost_trackable_token_usage > 0) return m.token_usage_cost_missing();
    return m.token_usage_cost_not_applicable();
  }

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: "Name",
      value: (item) => item.model_nickname,
      cell: (item) => {
        return createRender(ModelNameAndVendor, {
          model: {
            name: item.value.model_name,
            nickname: item.value.model_nickname,
            org: item.value.model_org ?? "",
            description: ""
          }
        });
      }
    }),

    table.column({
      header: m.input_tokens(),
      accessor: "input_token_usage",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: m.output_tokens(),
      accessor: "output_token_usage",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: m.usage_source(),
      accessor: "source_types",
      cell: (item) => sourceTypesLabel(item.value)
    }),

    table.column({
      header: m.total_tokens(),
      accessor: "total_token_usage",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: m.usage_cost(),
      id: "usage-cost",
      accessor: (item) => item,
      cell: (item) => costLabel(item.value)
    })
  ]);

  $: table.update(visibleItems);
</script>

<Table.Root {viewModel} resourceName={m.resource_models()} displayAs="list"></Table.Root>
{#if models.length > 10}
  <Button
    variant="outlined"
    class="h-12"
    on:click={() => {
      showAllItems = !showAllItems;
    }}
    >{showAllItems ? m.show_only_10_models() : m.show_all_models({ count: models.length })}</Button
  >
{/if}

{#if models.length === 0}
  <div class="py-12 text-center">
    <p class="text-gray-500">No model usage data available for this period</p>
  </div>
{/if}
