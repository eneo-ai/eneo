<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { AssistantResponse } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import dayjs from "dayjs";
  import { m } from "$lib/paraglide/messages";
  import QuestionDetails from "./QuestionDetails.svelte";
  import { createRender } from "svelte-headless-table";

  export let questions: AssistantResponse[];
  const table = Table.createWithResource(questions);

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.question(),
      value(item) {
        return item.question;
      },
      cell(item) {
        return createRender(QuestionDetails, {
          message: item.value
        });
      }
    }),
    table.column({
      header: m.created(),
      accessor: "created_at",
      cell: (item) => {
        return createRender(Table.FormattedCell, {
          value: dayjs(item.value).format("YYYY-MM-DD HH:mm"),
          monospaced: true
        });
      }
    })
  ]);

  $: table.update(questions);
</script>

<Table.Root
  {viewModel}
  resourceName="question"
  emptyMessage={m.no_questions_found_current_settings()}
></Table.Root>
