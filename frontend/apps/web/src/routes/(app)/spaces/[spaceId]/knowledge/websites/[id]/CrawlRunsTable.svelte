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
  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  // Set dayjs locale based on paraglide locale
  $: dayjs.locale(getLocale());

  const SKIPPED_PREFIX = "skipped";

  function isSkipped(crawl: CrawlRun): boolean {
    const reason = (crawl.result_location ?? "").toLowerCase();
    return crawl.status?.toLowerCase() === "failed" && reason.startsWith(SKIPPED_PREFIX);
  }

  function hasWarnings(crawl: CrawlRun): boolean {
    return (
      crawl.status?.toLowerCase() === "complete" &&
      ((crawl.pages_failed ?? 0) > 0 || (crawl.files_failed ?? 0) > 0)
    );
  }

  // Map crawl status to translated strings
  function translateStatus(crawl: CrawlRun): string {
    if (!crawl?.status) {
      return m.no_status_found();
    }

    if (isSkipped(crawl)) {
      return m.crawl_skipped();
    }

    switch (crawl.status?.toLowerCase()) {
      case "complete":
        return hasWarnings(crawl) ? m.crawl_completed_with_warnings() : m.complete();
      case "in progress":
        return m.in_progress();
      case "queued":
        return m.queued();
      case "failed":
      case "not found":
        return m.failed();
      default:
        return crawl.status ?? m.no_status_found();
    }
  }

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
        return createRender(Table.FormattedCell, {
          value: translateStatus(item.value),
          class: ""
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
        let value = m.started_time_ago({ timeAgo: dayjs().to(started) });

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
