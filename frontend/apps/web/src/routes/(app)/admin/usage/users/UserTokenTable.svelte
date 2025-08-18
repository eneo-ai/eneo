<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { UserTokenUsage, UserSortBy } from "@intric/intric-js";
  import { createRender } from "svelte-headless-table";
  import { Button, Table } from "@intric/ui";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import UsageBadgeWrapper from "./UsageBadgeWrapper.svelte";

  interface Props {
    users: UserTokenUsage[];
    totalUsers: number;
    page: number;
    perPage: number;
    sortBy: UserSortBy;
    sortOrder: "asc" | "desc";
    onUserClick: (user: UserTokenUsage) => void;
    onPageChange: (page: number) => void;
    onSortChange: (sortBy: UserSortBy, sortOrder: "asc" | "desc") => void;
  }

  const { users, totalUsers, page, perPage, onUserClick, onPageChange }: Props = $props();

  const table = Table.createWithResource<UserTokenUsage>([]);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: "User",
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
      header: "Usage Level",
      accessor: (item) => item.total_requests,
      id: "usage_level",
      cell: (item) => {
        return createRender(UsageBadgeWrapper, {
          requests: item.value
        });
      }
    }),

    table.column({
      header: "Input tokens",
      accessor: "total_input_tokens",
      id: "input_tokens",
      cell: (item) => formatNumber(item.value),
    }),

    table.column({
      header: "Output tokens",
      accessor: "total_output_tokens",
      id: "output_tokens",
      cell: (item) => formatNumber(item.value),
    }),

    table.column({
      header: "Total tokens",
      accessor: "total_tokens",
      id: "total_tokens",
      cell: (item) => formatNumber(item.value),
    }),

    table.column({
      header: "Requests",
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

<Table.Root {viewModel} resourceName="user" displayAs="list"></Table.Root>

{#if totalUsers > perPage}
  <div class="flex justify-center items-center mt-4">
    <Button
      variant="outlined"
      disabled={page === 1}
      onclick={() => onPageChange(1)}
    >
      First
    </Button>
    <Button
      variant="outlined"
      disabled={page === 1}
      onclick={() => onPageChange(page - 1)}
    >
      Previous
    </Button>
    <div class="px-4 py-2">{page} / {Math.ceil(totalUsers / perPage)}</div>
    <Button
      variant="outlined"
      disabled={page * perPage >= totalUsers}
      onclick={() => onPageChange(page + 1)}
    >
      Next
    </Button>
    <Button
      variant="outlined"
      disabled={page * perPage >= totalUsers}
      onclick={() => onPageChange(Math.ceil(totalUsers / perPage))}
    >
      Last
    </Button>
  </div>
{/if}

<!-- Empty state -->
{#if users.length === 0}
  <div class="text-center py-12">
    <div class="mx-auto w-12 h-12 bg-gray-100 dark:bg-gray-800 rounded-full flex items-center justify-center mb-4">
      <svg class="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z" />
      </svg>
    </div>
    <h3 class="text-lg font-medium text-gray-900 dark:text-gray-100 mb-2">No User Activity</h3>
    <p class="text-gray-500 dark:text-gray-400">No users have token usage in the selected time period.</p>
  </div>
{/if}
