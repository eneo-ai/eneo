<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import PromptActions from "./PromptActions.svelte";
  import { getPromptManager } from "../PromptManager";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import { onMount } from "svelte";
  import PromptTimestamp from "./PromptTimestamp.svelte";
  import PromptCreator from "./PromptCreator.svelte";
  import { m } from "$lib/paraglide/messages";

  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  const {
    state: { allPrompts },
    refreshPrompts
  } = getPromptManager();

  const table = Table.createWithStore(allPrompts);

  onMount(async () => {
    refreshPrompts();
  });

  const viewModel = table.createViewModel([
    table.column({
      header: m.created(),
      accessor: (item) => item,
      cell: (item) => {
        return createRender(PromptTimestamp, {
          prompt: item.value
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
    }),

    table.columnPrimary({
      header: m.author(),
      value: (item) => item.user.email,
      cell: (item) => {
        return createRender(PromptCreator, {
          user: item.value.user
        });
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(PromptActions, {
          prompt: item.value
        });
      }
    })
  ]);

  let allUniqueDates = new Set($allPrompts.map((prompt) => getUniqueDate(prompt.created_at)));

  function getUniqueDate(date: string | undefined | null) {
    return date ? dayjs(date).format("MMM D, YYYY") : m.prompts_without_date();
  }

  function createDateFilter(date: string) {
    return (value: { created_at: string }) => {
      return getUniqueDate(value.created_at) === date;
    };
  }
</script>

<div
  class="border-stronger bg-primary relative z-10 row-span-1 overflow-y-auto rounded-md border shadow-md"
>
  <Table.Root {viewModel} resourceName="prompt" displayAs="list" fitted actionPadding="tight">
    {#each allUniqueDates as date (date)}
      <Table.Group title={date} filterFn={createDateFilter(date)}></Table.Group>
    {/each}
  </Table.Root>
</div>
