<script lang="ts">
  import { Table } from "@intric/ui";
  import type { App, AppRunSparse } from "@intric/intric-js";
  import { createRender } from "svelte-headless-table";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import { getResultTitle } from "$lib/features/apps/getResultTitle";
  import { m } from "$lib/paraglide/messages";
  import ResultPrimaryCell from "./ResultPrimaryCell.svelte";
  import AppResultStatus from "$lib/features/apps/components/AppResultStatus.svelte";
  import ResultAction from "./ResultAction.svelte";

  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  export let results: AppRunSparse[];
  export let app: App;

  const table = Table.createWithResource(results);

  function onResultDeleted(result: { id: string }) {
    results = results.filter((r) => r.id !== result.id);
  }

  const viewModel = table.createViewModel([
    table.columnPrimary({
      header: m.name(),
      value: (item) => getResultTitle(item),
      cell: (item) => {
        return createRender(ResultPrimaryCell, {
          run: item.value,
          app
        });
      }
    }),
    table.column({
      header: m.status(),
      accessor: (item) => item,
      cell: (item) => {
        return createRender(AppResultStatus, {
          run: item.value
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
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(ResultAction, {
          result: item.value,
          onResultDeleted
        });
      }
    })
  ]);

  $: table.update(results);
</script>

<Table.Root {viewModel} resourceName="result" emptyMessage={m.no_previous_results_found()}></Table.Root>
