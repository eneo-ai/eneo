<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import { getInsightsService } from "../InsightsService.svelte";
  import { toStore } from "svelte/store";
  import InsightsConversationPrimaryCell from "./InsightsConversationPrimaryCell.svelte";
  import { m } from "$lib/paraglide/messages";

  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  const insights = getInsightsService();
  const table = Table.createWithStore(toStore(() => insights.conversations));

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
          value: dayjs(item.value.created_at).format("YYYY-MM-DD HH:mm"),
          monospaced: true
        });
      },

      plugins: {
        tableFilter: {
          getFilterValue(item) {
            return dayjs(item.created_at).format("YYYY-MM-DD HH:mm");
          }
        },
        sort: {
          getSortValue(item) {
            return dayjs(item.created_at).format("YYYY-MM-DD HH:mm");
          }
        }
      }
    })
  ]);
</script>

<div
  class="border-stronger bg-primary relative z-10 row-span-1 overflow-y-auto rounded-md border shadow-md"
>
  <Table.Root
    {viewModel}
    resourceName="question"
    displayAs="list"
    fitted
    actionPadding="tight"
    emptyMessage={m.no_questions_found_timeframe()}
  ></Table.Root>

  <div class="text-secondary flex-col pt-8 pb-12">
    <div class="flex flex-col items-center justify-center gap-2">
      {#if insights.hasMoreConversations}
        <Button
          variant="primary-outlined"
          on:click={() => insights.loadMoreConversations()}
          aria-label={m.load_more_conversations()}
        >
          {#if insights.loadMoreConversations.isLoading}
            {m.loading()}
          {:else}
            {m.load_more_conversations()}
          {/if}
        </Button>
        <p role="status" aria-live="polite">
          {m.loaded_conversations_count({ loaded: insights.conversations.length, total: insights.totalConversationCount })}
        </p>
      {:else if insights.totalConversationCount > 0}
        <p role="status" aria-live="polite">
          {m.loaded_all_conversations({ total: insights.totalConversationCount })}
        </p>
      {/if}
    </div>
  </div>
</div>
