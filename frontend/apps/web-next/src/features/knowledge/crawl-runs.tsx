"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  proportional,
  useTableSortable,
  useTableSortableState,
  type TableColumn
} from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { SearchX } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { formatDuration } from "@/lib/format";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { CrawlRunDetailsDialog } from "./crawl-run-details";
import { crawlRunState, type CrawlFailureKind } from "./crawl-run-state";
import { CrawlFailureActions, CrawlRunStatusLabel } from "./crawl-run-ui";
import type { CrawlRun } from "./knowledge";
import {
  CRAWL_RUN_COMPARATORS,
  CRAWL_RUN_DEFAULT_SORT,
  type CrawlRunSortKey
} from "./knowledge-sort";
import { filterCrawlRuns } from "./table-controls";
import { KnowledgeLabel, KnowledgeTableControls } from "./table-controls-ui";

/** Which run's details to show, opened on the failures of one kind. */
export type RunSelection = { run: CrawlRun; kind: CrawlFailureKind | null };

/** When the run started, as a button that opens its details. */
function CrawlStartedCell({ run, onSelect }: { run: CrawlRun; onSelect: () => void }) {
  const t = useTranslations();
  const date = useClientTimeText(run.created_at, "date_time");
  if (!run.created_at) return "—";
  return (
    <Button
      variant="ghost"
      size="sm"
      label={t("crawl_details_title", { date: date ?? "" })}
      onClick={onSelect}
    >
      <ClientTime value={run.created_at} format="date_time" />
    </Button>
  );
}

/**
 * What the run did: pages and files that succeeded, pages left unchanged,
 * and links to what failed. Ported from CrawlResultCell.svelte.
 */
function CrawlResultCell({
  run,
  onShowFailures
}: {
  run: CrawlRun;
  onShowFailures: (kind: CrawlFailureKind | null) => void;
}) {
  const t = useTranslations();
  const state = crawlRunState(run);
  const pages = run.pages_crawled ?? 0;
  const files = run.files_downloaded ?? 0;
  const unchanged = run.pages_unchanged ?? 0;
  const showsCounts =
    state === "succeeded" ||
    state === "partial" ||
    state === "running" ||
    state === "finalizing" ||
    state === "stopping";
  const successLabel =
    pages > 0 && files > 0
      ? t("pages_and_files_succeeded", { pages, files })
      : pages > 0
        ? t("pages_succeeded", { count: pages })
        : t("files_succeeded", { count: files });

  return (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
      {showsCounts && (pages > 0 || files > 0) ? (
        <KnowledgeLabel tone="success" label={successLabel} />
      ) : null}
      {(showsCounts || state === "unchanged") && unchanged > 0 ? (
        <KnowledgeLabel tone="neutral" label={t("pages_unchanged_count", { count: unchanged })} />
      ) : null}
      {!(showsCounts && (pages > 0 || files > 0)) && !(state === "unchanged" && unchanged > 0) ? (
        <span className="text-ax-text-secondary">—</span>
      ) : null}
      <CrawlFailureActions run={run} onSelect={onShowFailures} />
    </div>
  );
}

/** How long a finished run took; for a running one, when it started. */
function CrawlDurationCell({ crawl }: { crawl: CrawlRun }) {
  const t = useTranslations();
  if (crawl.finished_at && crawl.created_at) {
    return formatDuration(crawl.created_at, crawl.finished_at);
  }
  if (!crawl.created_at) return "—";
  const startedAt = crawl.created_at;
  return t.rich("space_crawl_started_ago", {
    time: () => <ClientTime value={startedAt} format="relative" />
  });
}

/**
 * A website's crawl history: a filter box and a bordered Astryx table that
 * sorts by its column headers, newest crawl first. A run's date and its
 * failure links open the run's details; `onRerun` adds "run the whole
 * website again" to them.
 */
export function CrawlRunsTable({ runs, onRerun }: { runs: CrawlRun[]; onRerun?: () => void }) {
  const t = useTranslations();
  const [filter, setFilter] = useState("");
  const [selection, setSelection] = useState<RunSelection | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const { sortedData, sortConfig } = useTableSortableState<CrawlRun, CrawlRunSortKey>({
    data: filterCrawlRuns(runs, filter),
    defaultSort: CRAWL_RUN_DEFAULT_SORT,
    comparators: CRAWL_RUN_COMPARATORS
  });
  const sortPlugin = useTableSortable<CrawlRun, CrawlRunSortKey>(sortConfig);

  if (runs.length === 0) {
    return <EmptyState title={t("this_website_not_crawled_before")} />;
  }

  const select = (run: CrawlRun, kind: CrawlFailureKind | null) => {
    setSelection({ run, kind });
    setDetailsOpen(true);
  };

  const columns: TableColumn<CrawlRun>[] = [
    {
      key: "started",
      header: t("fix_crawl_started_column"),
      width: proportional(1),
      sortable: true,
      renderCell: (run) => <CrawlStartedCell run={run} onSelect={() => select(run, null)} />
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      sortable: true,
      renderCell: (run) => <CrawlRunStatusLabel run={run} />
    },
    {
      key: "results",
      header: t("results"),
      width: proportional(2),
      sortable: true,
      renderCell: (run) => (
        <CrawlResultCell run={run} onShowFailures={(kind) => select(run, kind)} />
      )
    },
    {
      key: "duration",
      header: t("duration"),
      width: proportional(1),
      sortable: true,
      renderCell: (run) => <CrawlDurationCell crawl={run} />
    }
  ];

  return (
    <div className="flex flex-col gap-4">
      <KnowledgeTableControls
        filterValue={filter}
        onFilterChange={setFilter}
        filterLabel={t("fix_crawls_filter_label")}
        filterPlaceholder={t("space_filter_crawls_placeholder")}
        resultCount={sortedData.length}
      />
      {sortedData.length === 0 ? (
        <EmptyState
          icon={<SearchX />}
          title={t("ui_no_items_matching", { resourceNamePlural: t("resource_crawls") })}
          isCompact
        />
      ) : (
        <SpaceTableFrame>
          {/* No heading above it: the table fills the website page's
              "Indexeringar" tab, so it takes the tab's name. */}
          <Table
            data={sortedData}
            columns={columns}
            idKey="id"
            aria-label={t("crawls")}
            plugins={{ sort: sortPlugin }}
          />
        </SpaceTableFrame>
      )}
      {selection ? (
        <CrawlRunDetailsDialog
          run={selection.run}
          initialKind={selection.kind}
          isOpen={detailsOpen}
          onOpenChange={setDetailsOpen}
          onRerun={onRerun}
        />
      ) : null}
    </div>
  );
}
