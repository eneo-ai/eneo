<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { UserTokenUsage, UserSortBy } from "@eneo/eneo-js";
  import { createRender } from "svelte-headless-table";
  import { Button, Table } from "@eneo/ui";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import { m } from "$lib/paraglide/messages";
  import UsageBadgeWrapper from "./UsageBadgeWrapper.svelte";
  import EstimatedCostCell from "../tokens/EstimatedCostCell.svelte";
  import { estimateCostFromTokens, formatCostUSD } from "$lib/features/ai-models/formatModelStats";
  import type { CostRateMap } from "$lib/features/ai-models/costRates";

  interface Props {
    users: UserTokenUsage[];
    totalUsers: number;
    page: number;
    perPage: number;
    sortBy: UserSortBy;
    sortOrder: "asc" | "desc";
    highThreshold: number;
    mediumThreshold: number;
    costRates: CostRateMap;
    onUserClick: (user: UserTokenUsage) => void;
    onPageChange: (page: number) => void;
    onSortChange: (sortBy: UserSortBy, sortOrder: "asc" | "desc") => void;
  }

  const {
    users,
    totalUsers,
    page,
    perPage,
    highThreshold,
    mediumThreshold,
    costRates,
    onUserClick,
    onPageChange
  }: Props = $props();

  // Sum the per-model estimated cost for one user. A user's models_used array
  // already breaks down tokens per model, so we look up the rate for each and
  // accumulate. Returns null if every model is missing rates so callers can
  // render a neutral chip rather than a misleading "$0".
  function estimateUserCost(user: UserTokenUsage): number | null {
    let total = 0;
    let anyKnown = false;
    for (const usage of user.models_used) {
      const rates = costRates.get(usage.model_id);
      if (!rates) continue;
      const cost = estimateCostFromTokens(usage.input_token_usage, usage.output_token_usage, rates);
      if (cost == null) continue;
      total += cost;
      anyKnown = true;
    }
    return anyKnown ? total : null;
  }

  const table = Table.createWithResource<UserTokenUsage>([]);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.user(),
      value: (item) => item.username,
      cell: (item) => {
        return createRender(Table.ButtonCell, {
          label: item.value.username,
          onclick: () => {
            onUserClick(item.value);
          }
        });
      }
    }),

    table.column({
      header: m.usage_level(),
      accessor: (item) => item.total_tokens,
      id: "usage_level",
      cell: (item) => {
        return createRender(UsageBadgeWrapper, {
          tokens: item.value,
          highThreshold,
          mediumThreshold
        });
      }
    }),

    table.column({
      header: m.input_tokens(),
      accessor: "total_input_tokens",
      id: "input_tokens",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: m.output_tokens(),
      accessor: "total_output_tokens",
      id: "output_tokens",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: m.total_tokens(),
      accessor: "total_tokens",
      id: "total_tokens",
      cell: (item) => formatNumber(item.value)
    }),

    table.column({
      header: m.requests(),
      accessor: "total_requests",
      id: "requests",
      cell: (item) => formatNumber(item.value),
      plugins: {
        sort: {
          getSortValue(item) {
            return item;
          }
        }
      }
    }),

    table.column({
      header: m.estimated_cost(),
      accessor: (user) => user,
      id: "estimated_cost",
      cell: (item) =>
        createRender(EstimatedCostCell, { label: formatCostUSD(estimateUserCost(item.value)) }),
      plugins: {
        sort: {
          getSortValue(value) {
            return estimateUserCost(value) ?? -1;
          }
        }
      }
    })
  ]);

  $effect(() => {
    table.update(users);
  });
</script>

<Table.Root {viewModel} resourceName={m.resource_users()} displayAs="list"></Table.Root>

{#if totalUsers > perPage}
  <div class="mt-4 flex items-center justify-center">
    <Button variant="outlined" disabled={page === 1} onclick={() => onPageChange(1)}>
      {m.first()}
    </Button>
    <Button variant="outlined" disabled={page === 1} onclick={() => onPageChange(page - 1)}>
      {m.previous()}
    </Button>
    <div class="px-4 py-2">{page} / {Math.ceil(totalUsers / perPage)}</div>
    <Button
      variant="outlined"
      disabled={page * perPage >= totalUsers}
      onclick={() => onPageChange(page + 1)}
    >
      {m.next()}
    </Button>
    <Button
      variant="outlined"
      disabled={page * perPage >= totalUsers}
      onclick={() => onPageChange(Math.ceil(totalUsers / perPage))}
    >
      {m.last()}
    </Button>
  </div>
{/if}
