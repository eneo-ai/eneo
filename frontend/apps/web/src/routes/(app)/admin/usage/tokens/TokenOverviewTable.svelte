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
  import { estimateCostFromTokens, formatCostUSD } from "$lib/features/ai-models/formatModelStats";
  import type { CostRateMap } from "$lib/features/ai-models/costRates";
  import EstimatedCostCell from "./EstimatedCostCell.svelte";

  export let tokenStats: TokenUsageSummary;
  export let costRates: CostRateMap;

  $: models = tokenStats.models.toSorted((a, b) =>
    (a.model_org ?? "").localeCompare(b.model_org ?? "")
  );

  let showAllItems = false;

  $: visibleItems = showAllItems ? models : models.slice(0, 10);

  function estimateCostText(modelId: string, inputTokens: number, outputTokens: number): string {
    const rates = costRates.get(modelId);
    if (!rates) return "–";
    const cost = estimateCostFromTokens(inputTokens, outputTokens, rates);
    return formatCostUSD(cost);
  }

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
      header: m.total_tokens(),
      accessor: "total_token_usage",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: m.estimated_cost(),
      accessor: (item) => item,
      cell: (item) =>
        createRender(EstimatedCostCell, {
          label: estimateCostText(
            item.value.model_id,
            item.value.input_token_usage,
            item.value.output_token_usage
          )
        }),
      plugins: {
        sort: {
          getSortValue(value) {
            const rates = costRates.get(value.model_id);
            if (!rates) return -1;
            return (
              estimateCostFromTokens(value.input_token_usage, value.output_token_usage, rates) ?? -1
            );
          }
        }
      }
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
    <p class="text-gray-500">{m.usage_no_model_data_available()}</p>
  </div>
{/if}
