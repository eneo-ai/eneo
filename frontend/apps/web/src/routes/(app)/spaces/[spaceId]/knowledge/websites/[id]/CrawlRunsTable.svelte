<script lang="ts">
  import type { CrawlRun } from "@intric/intric-js";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import "dayjs/locale/sv";
  import "dayjs/locale/en";
  import CrawlResultCell from "./CrawlResultCell.svelte";
  import CrawlStatusCell from "./CrawlStatusCell.svelte";
  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  // Set dayjs locale based on paraglide locale
  // eslint-disable-next-line svelte/no-immutable-reactive-statements
  $: dayjs.locale(getLocale());

  export let runs: CrawlRun[];
  const table = Table.createWithResource(runs);

  const viewModel = table.createViewModel([
    table.column({
      accessor: "created_at",
      header: m.started(),
      cell: (item) => {
        return createRender(Table.FormattedCell, {
          value: dayjs(item.value).format("YYYY-MM-DD HH:mm"),
          monospaced: true
        });
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.status(),
      cell: (item) => {
        return createRender(CrawlStatusCell, {
          crawl: item.value
        });
      },
      plugins: {
        sort: {
          getSortValue(value) {
            return value.status ?? "";
          }
        }
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.results(),
      cell: (item) => {
        return createRender(CrawlResultCell, {
          crawl: item.value
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
        const started = dayjs(item.value.created_at);
        let value: string = m.started_time_ago({ timeAgo: dayjs().to(started) });

        if (item.value.finished_at) {
          const finished = dayjs(item.value.finished_at);
          value = started.to(finished, true);
        }

        return createRender(Table.FormattedCell, {
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
