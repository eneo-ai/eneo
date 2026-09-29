<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { UserTokenUsage, UserSortBy } from "@eneo/eneo-js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Button } from "$lib/components/ui/button";
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

  let {
    users,
    totalUsers,
    page,
    perPage,
    sortBy,
    sortOrder,
    highThreshold,
    mediumThreshold,
    costRates,
    onUserClick,
    onPageChange,
    onSortChange
  }: Props = $props();

  function sort(field: UserSortBy) {
    onSortChange(
      field,
      sortBy === field
        ? sortOrder === "asc"
          ? "desc"
          : "asc"
        : field === "username"
          ? "asc"
          : "desc"
    );
  }

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
</script>

{#snippet sortHeader(field: UserSortBy, label: string)}
  <Table.Head
    aria-sort={sortBy === field ? (sortOrder === "asc" ? "ascending" : "descending") : "none"}
  >
    <Button variant="ghost" class="-ml-2" onclick={() => sort(field)}>
      {label}<span aria-hidden="true"
        >{sortBy === field ? (sortOrder === "asc" ? "↑" : "↓") : "↕"}</span
      >
    </Button>
  </Table.Head>
{/snippet}

<div class="border-default bg-primary overflow-hidden rounded-lg border">
  <Table.Root class="[&_td]:px-4 [&_td]:py-3 [&_th]:px-4">
    <Table.Caption class="sr-only">{m.usage_by_user()}</Table.Caption>
    <Table.Header
      ><Table.Row>
        {@render sortHeader("username", m.user())}
        <Table.Head>{m.usage_level()}</Table.Head>
        {@render sortHeader("input_tokens", m.input_tokens())}
        {@render sortHeader("output_tokens", m.output_tokens())}
        {@render sortHeader("total_tokens", m.total_tokens())}
        {@render sortHeader("requests", m.requests())}
        <Table.Head>{m.estimated_cost()}</Table.Head>
      </Table.Row></Table.Header
    >
    <Table.Body>
      {#each users as user (user.user_id)}
        <Table.Row>
          <Table.Cell>
            <Button variant="link" class="h-auto p-0" onclick={() => onUserClick(user)}
              >{user.username}</Button
            >
            {#if user.email !== user.username}<div class="text-muted-foreground text-xs">
                {user.email}
              </div>{/if}
          </Table.Cell>
          <Table.Cell
            ><UsageBadgeWrapper
              tokens={user.total_tokens}
              {highThreshold}
              {mediumThreshold}
            /></Table.Cell
          >
          <Table.Cell class="tabular-nums">{formatNumber(user.total_input_tokens)}</Table.Cell>
          <Table.Cell class="tabular-nums">{formatNumber(user.total_output_tokens)}</Table.Cell>
          <Table.Cell class="tabular-nums">{formatNumber(user.total_tokens)}</Table.Cell>
          <Table.Cell class="tabular-nums">{formatNumber(user.total_requests)}</Table.Cell>
          <Table.Cell
            ><EstimatedCostCell label={formatCostUSD(estimateUserCost(user))} /></Table.Cell
          >
        </Table.Row>
      {:else}
        <Table.Row
          ><Table.Cell colspan={7} class="h-24 text-center">{m.no_results()}</Table.Cell></Table.Row
        >
      {/each}
    </Table.Body>
  </Table.Root>
</div>

{#if totalUsers > perPage || page > 1}
  <nav
    class="mt-4 flex flex-wrap items-center justify-center gap-2"
    aria-label={m.admin_users_pagination()}
  >
    <Button variant="outline" disabled={page === 1} onclick={() => onPageChange(1)}
      >{m.first()}</Button
    >
    <Button variant="outline" disabled={page === 1} onclick={() => onPageChange(page - 1)}
      >{m.previous()}</Button
    >
    <span class="px-2 text-sm tabular-nums"
      >{page} / {Math.max(1, Math.ceil(totalUsers / perPage))}</span
    >
    <Button
      variant="outline"
      disabled={page * perPage >= totalUsers}
      onclick={() => onPageChange(page + 1)}>{m.next()}</Button
    >
    <Button
      variant="outline"
      disabled={page * perPage >= totalUsers}
      onclick={() => onPageChange(Math.ceil(totalUsers / perPage))}>{m.last()}</Button
    >
  </nav>
{/if}
