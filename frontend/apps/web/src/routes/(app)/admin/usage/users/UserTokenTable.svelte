<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { UserTokenUsage, UserSortBy } from "@intric/intric-js";
  import { createRender } from "svelte-headless-table";
  import { Button, Table } from "@intric/ui";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import { m } from "$lib/paraglide/messages";
  import UsageBadgeWrapper from "./UsageBadgeWrapper.svelte";

  interface Props {
    users: UserTokenUsage[];
    totalUsers: number;
    page: number;
    perPage: number;
    sortBy: UserSortBy;
    sortOrder: "asc" | "desc";
    highThreshold: number;
    mediumThreshold: number;
    onUserClick: (user: UserTokenUsage) => void;
    onPageChange: (page: number) => void;
    onSortChange: (sortBy: UserSortBy, sortOrder: "asc" | "desc") => void;
  }

  const { users, totalUsers, page, perPage, highThreshold, mediumThreshold, onUserClick, onPageChange }: Props = $props();

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
