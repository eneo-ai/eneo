<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { getInsightsService } from "../InsightsService.svelte";
  import { toStore } from "svelte/store";
  import InsightsConversationPrimaryCell from "./InsightsConversationPrimaryCell.svelte";
  import { m } from "$lib/paraglide/messages";

  const insights = getInsightsService();
  const table = Table.createWithStore(toStore(() => insights.conversations), 999999, {
    serverSideFilter: true
  });
  const dateFormatter = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });

  function formatDate(dateInput: string) {
    return dateFormatter.format(new Date(dateInput));
  }

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.question(),
      value: (item) => item.name,
      cell: (item) => {
        return createRender(InsightsConversationPrimaryCell, {
          conversation: item.value
        });
      }
    }),

    table.column({
      header: m.created(),
      accessor: (item) => item,
      cell: (item) => {
        return createRender(Table.FormattedCell, {
          value: formatDate(item.value.created_at),
          monospaced: true
        });
      },

      plugins: {
        tableFilter: {
          getFilterValue(item) {
            return formatDate(item.created_at);
          }
        },
        sort: {
          getSortValue(item) {
            return new Date(item.created_at).getTime();
          }
        }
      }
    })
  ]);

  export const filterValue = viewModel.pluginStates.tableFilter.filterValue;

  let debounceTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const unsubscribe = filterValue.subscribe((value: string) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        insights.searchConversations(value);
      }, 250);
    });

    return () => {
      clearTimeout(debounceTimer);
      unsubscribe();
    };
  });
</script>

<div
  class="border-stronger bg-primary relative z-10 row-span-1 overflow-y-auto rounded-md border shadow-md"
  style="content-visibility: auto;"
  aria-busy={insights.loadMoreConversations.isLoading || insights.searchConversations.isLoading}
>
  <Table.Root
    {viewModel}
    resourceName={m.resource_questions()}
    displayAs="list"
    fitted
    actionPadding="tight"
    emptyMessage={m.no_questions_found_timeframe()}
  ></Table.Root>

  <div class="text-secondary flex-col pt-8 pb-12">
    <div class="flex flex-col items-center justify-center gap-2">
      {#if insights.conversationListError}
        <p class="text-red-700" role="alert">{m.error_connecting_to_server()}</p>
      {:else if insights.searchConversations.isLoading}
        <p role="status" aria-live="polite">{m.loading_ellipsis()}</p>
      {:else if insights.hasMoreConversations}
        <Button
          variant="primary-outlined"
          on:click={() => insights.loadMoreConversations()}
          aria-label={m.load_more_conversations()}
          disabled={insights.loadMoreConversations.isLoading || insights.searchConversations.isLoading}
        >
          {#if insights.loadMoreConversations.isLoading}
            {m.loading()}
          {:else}
            {m.load_more_conversations()}
          {/if}
        </Button>
        <p role="status" aria-live="polite">
          {m.loaded_conversations_count({
            loaded: insights.conversations.length,
            total: insights.totalConversationCount
          })}
        </p>
      {:else if insights.totalConversationCount > 0}
        <p role="status" aria-live="polite">
          {m.loaded_all_conversations({ total: insights.totalConversationCount })}
        </p>
      {/if}
    </div>
  </div>
</div>
