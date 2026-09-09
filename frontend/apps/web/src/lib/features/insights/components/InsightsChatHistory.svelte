<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.

    The operator's previous analyses for the current chat partner, in the
    same table as the chat history: open one to resume it, or delete it.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button, Table } from "@eneo/ui";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { createRender } from "svelte-headless-table";
  import { toStore } from "svelte/store";
  import dayjs from "dayjs";
  import { getInsightsChatService } from "../InsightsChatService.svelte";
  import InsightsChatHistoryActions from "./InsightsChatHistoryActions.svelte";

  type Props = {
    /** Called when the operator picks an analysis to resume. */
    onOpen: (conversation: { id: string }) => void;
  };

  let { onOpen }: Props = $props();

  const chat = getInsightsChatService();
  const table = Table.createWithStore(toStore(() => chat.history));

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => item.name,
      cell: (item) =>
        createRender(Table.ButtonCell, {
          label: item.value.name,
          onclick() {
            onOpen(item.value);
          }
        }),
      sortable: false
    }),
    table.column({
      header: m.created(),
      accessor: "created_at",
      cell: (item) =>
        createRender(Table.FormattedCell, {
          value: item.value ? dayjs(item.value).format("YYYY-MM-DD HH:mm") : "",
          monospaced: true
        })
    }),
    table.columnActions({
      cell: (item) => createRender(InsightsChatHistoryActions, { conversation: item.value })
    })
  ]);
</script>

<div class="flex flex-col gap-3">
  {#if chat.historyError}
    <p class="text-negative-default text-sm" role="alert">{m.insights_chat_history_error()}</p>
  {:else if chat.loadHistory.isLoading && chat.history.length === 0}
    <div class="text-secondary flex items-center gap-2 py-6 text-sm" role="status">
      <IconLoadingSpinner class="size-4 animate-spin" aria-hidden="true"></IconLoadingSpinner>
      <span>{m.loading()}</span>
    </div>
  {:else}
    <Table.Root
      {viewModel}
      resourceName={m.insights_chat_history()}
      emptyMessage={m.insights_chat_empty_history()}
    ></Table.Root>
    {#if chat.hasMoreHistory}
      <Button
        variant="outlined"
        class="self-start"
        disabled={chat.loadHistory.isLoading}
        onclick={() => chat.loadHistory(true)}>{m.insights_chat_load_more()}</Button
      >
    {/if}
  {/if}
</div>
