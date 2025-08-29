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

  export let tokenStats: TokenUsageSummary;

  $: models = tokenStats.models.toSorted((a, b) =>
    (a.model_org ?? "").localeCompare(b.model_org ?? "")
  );

  let showAllItems = false;

  $: visibleItems = showAllItems ? models : models.slice(0, 10);

  const table = Table.createWithResource(visibleItems);

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
      },
      plugins: {
        sort: {
          getSortValue(item) {
            return item.model_nickname ?? "";
          }
        }
      }
    }),

    table.column({
      header: "Input tokens",
      accessor: "input_token_usage",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: "Output tokens",
      accessor: "output_token_usage",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: "Total tokens",
      accessor: "total_token_usage",
      cell: (item) => formatNumber(item.value)
    })
  ]);

  $: table.update(visibleItems);
</script>

<Table.Root {viewModel} resourceName="model" displayAs="list"></Table.Root>
{#if models.length > 10}
  <Button
    variant="outlined"
    class="h-12"
    on:click={() => {
      showAllItems = !showAllItems;
    }}>{showAllItems ? "Show only 10 models" : `Show all ${models.length} models`}</Button
  >
{/if}

{#if models.length === 0}
    <div class="text-center py-12">
        <p class="text-gray-500">No model usage data available for this period</p>
    </div>
{/if}