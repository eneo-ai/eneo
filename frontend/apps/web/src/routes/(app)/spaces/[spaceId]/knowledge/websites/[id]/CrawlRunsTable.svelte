<script lang="ts">
  import {
    formatDateTime,
    formatRelativeTime,
    formatDuration
  } from "$lib/core/formatting/dateTime";
  import type { CrawlRun } from "@eneo/eneo-js";
  import * as Table from "$lib/components/resource-table/index.js";
  import { m } from "$lib/paraglide/messages";

  import CrawlResultCell from "./CrawlResultCell.svelte";

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
        return Table.renderComponent(Table.FormattedCell, {
          value: formatDateTime(item.value),
          monospaced: true
        });
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.status(),
      cell: (item) => {
        return Table.renderComponent(Table.FormattedCell, {
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
        return Table.renderComponent(CrawlResultCell, {
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
        let value: string = m.started_time_ago({
          timeAgo: formatRelativeTime(item.value.created_at)
        });

        if (item.value.finished_at) {
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
