<script lang="ts">
  import {
    formatDateTime,
    formatRelativeTime,
    formatDuration
  } from "$lib/core/formatting/dateTime";
  import type { CrawlResourceFailure, CrawlRun } from "@eneo/eneo-js";
  import * as Table from "$lib/components/resource-table/index.js";
  import { m } from "$lib/paraglide/messages";

  import CrawlResultCell from "./CrawlResultCell.svelte";
  import CrawlRunDetails from "$lib/features/knowledge/CrawlRunDetails.svelte";
  import { crawlRunState, crawlRunStateLabel } from "$lib/features/knowledge/crawlRunState";

  export let runs: CrawlRun[];
  export let onrerun: (() => void) | undefined = undefined;
  let initialKind: CrawlResourceFailure["kind"] | null = null;

  function showFailures(run: CrawlRun, kind: CrawlResourceFailure["kind"] | null = null) {
    selectedRun = run;
    initialKind = kind;
    detailsOpen = true;
  }
  let selectedRun: CrawlRun | null = null;
  let detailsOpen = false;
  const table = Table.createWithResource(runs);

  const viewModel = table.createViewModel([
    table.column({
      accessor: (run) => run,
      id: "created_at",
      header: m.started(),
      cell: (item) => {
        return Table.renderComponent(Table.ButtonCell, {
          label: formatDateTime(item.value.created_at),
          onclick: () => showFailures(item.value)
        });
      },
      plugins: {
        sort: { getSortValue: (run) => run.created_at ?? "" },
        tableFilter: { getFilterValue: (run) => formatDateTime(run.created_at) }
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.status(),
      cell: (item) => {
        return Table.renderComponent(Table.FormattedCell, {
          value: crawlRunStateLabel(crawlRunState(item.value)),
          class: ""
        });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return crawlRunState(value);
          }
        }
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.results(),
      cell: (item) => {
        return Table.renderComponent(CrawlResultCell, {
          crawl: item.value,
          onshowFailures: (kind) => showFailures(item.value, kind)
        });
      },
      plugins: { sort: { disable: true } }
    }),

    table.column({
      accessor: (item) => item,
      header: m.duration(),
      plugins: {
        sort: { disable: true },
        tableFilter: {
          getFilterValue() {
            return "";
          }
        }
      },
      cell: (item) => {
        let value: string = m.started_time_ago({
          timeAgo: formatRelativeTime(item.value.created_at)
        });

        if (item.value.finished_at && item.value.created_at) {
          value = formatDuration(
            new Date(item.value.finished_at).getTime() - new Date(item.value.created_at).getTime()
          );
        }

        return Table.renderComponent(Table.FormattedCell, {
          value
        });
      }
    })
  ]);

  $: table.update(runs);
</script>

<Table.Root
  {viewModel}
  filter
  emptyMessage={m.this_website_not_crawled_before()}
  resourceName="crawl"
></Table.Root>

{#if selectedRun}
  <CrawlRunDetails run={selectedRun} bind:open={detailsOpen} {initialKind} {onrerun} />
{/if}
