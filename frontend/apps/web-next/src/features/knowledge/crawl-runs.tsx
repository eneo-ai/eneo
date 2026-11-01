"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  pixel,
  proportional,
  useTableSortable,
  useTableSortableState,
  type TableColumn
} from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { SearchX } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { formatDuration } from "@/lib/format";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { useFilterShown } from "@/features/spaces/resource-filter-input";
import { TableFrame } from "@/components/composites/table-frame";
import { CrawlRunDetailsDialog } from "./crawl-run-details";
import { crawlRunState, hasCrawlIssues, type CrawlFailureKind } from "./crawl-run-state";
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
function CrawlStartedCell({
  run,
  onSelect,
  className
}: {
  run: CrawlRun;
  onSelect: () => void;
  className?: string;
}) {
  const t = useTranslations();
  const date = useClientTimeText(run.created_at, "date_time");
  if (!run.created_at) return "—";
  return (
    <Button
      variant="ghost"
      size="sm"
      label={t("crawl_details_title", { date: date ?? "" })}
      onClick={onSelect}
      className={className}
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
  onShowFailures,
  inRow = false
}: {
  run: CrawlRun;
  onShowFailures: (kind: CrawlFailureKind | null) => void;
  /** A phone row leaves the line out while the run has no result; a table cell says "—". */
  inRow?: boolean;
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
  const succeeded = showsCounts && (pages > 0 || files > 0);
  const unchangedShown = (showsCounts || state === "unchanged") && unchanged > 0;
  if (inRow && !succeeded && !unchangedShown && !hasCrawlIssues(run)) return null;

  return (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
      {succeeded ? <KnowledgeLabel tone="success" label={successLabel} /> : null}
      {unchangedShown ? (
        <KnowledgeLabel tone="neutral" label={t("pages_unchanged_count", { count: unchanged })} />
      ) : null}
      {!inRow && !succeeded && !(state === "unchanged" && unchanged > 0) ? (
        <span className="text-ax-text-secondary">—</span>
      ) : null}
      <CrawlFailureActions
        run={run}
        onSelect={onShowFailures}
        // A ghost button alone on the line starts on the row's 16 px line, as the date above it.
        className={
          inRow && !succeeded && !unchangedShown && !(run.pages_failed || run.files_failed)
            ? "-ms-3"
            : undefined
        }
      />
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
  const phone = useMediaMatch(PHONE_QUERY);
  // A phone shows the filter only for a long history; a hidden filter no longer applies.
  const filterShown = useFilterShown(runs.length);
  const { sortedData, sortConfig } = useTableSortableState<CrawlRun, CrawlRunSortKey>({
    data: filterCrawlRuns(runs, filterShown ? filter : ""),
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
      width: pixel(216),
      sortable: true,
      renderCell: (run) => <CrawlStartedCell run={run} onSelect={() => select(run, null)} />
    },
    {
      key: "status",
      header: t("status"),
      width: pixel(136),
      sortable: true,
      renderCell: (run) => <CrawlRunStatusLabel run={run} />
    },
    {
      key: "results",
      header: t("results"),
      width: proportional(1, { minWidth: 200 }),
      sortable: true,
      renderCell: (run) => (
        <CrawlResultCell run={run} onShowFailures={(kind) => select(run, kind)} />
      )
    },
    {
      key: "duration",
      header: t("duration"),
      width: pixel(128),
      sortable: true,
      renderCell: (run) => <CrawlDurationCell crawl={run} />
    }
  ];

  return (
    <div className="flex flex-col gap-4">
      {filterShown ? (
        <KnowledgeTableControls
          filterValue={filter}
          onFilterChange={setFilter}
          filterLabel={t("fix_crawls_filter_label")}
          filterPlaceholder={t("space_filter_crawls_placeholder")}
          resultCount={sortedData.length}
        />
      ) : null}
      {sortedData.length === 0 ? (
        <EmptyState
          icon={<SearchX />}
          title={t("ui_no_items_matching", { resourceNamePlural: t("resource_crawls") })}
          isCompact
        />
      ) : (
        <>
          {phone ? (
            // A phone (decision 9): a block per run, newest first (the table's default order):
            // when it started and its state, what it did, how long it took. A table of four
            // wide columns cut the result and lost the duration off the screen.
            <ul
              aria-label={t("crawls")}
              className="border-ax-border divide-ax-border -mx-4 divide-y border-y"
            >
              {sortedData.map((run) => (
                <li key={run.id} className="flex flex-col gap-1.5 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    {/* The ghost button's padding pulled back: the date starts on the
                        row's 16 px line, with the lines under it. */}
                    <CrawlStartedCell
                      run={run}
                      onSelect={() => select(run, null)}
                      className="-ms-3"
                    />
                    <CrawlRunStatusLabel run={run} />
                  </div>
                  <CrawlResultCell run={run} onShowFailures={(kind) => select(run, kind)} inRow />
                  <span className="text-ax-text-secondary text-xs">
                    {/* A running one says when it started, which needs no label. */}
                    {run.finished_at ? `${t("duration")}: ` : null}
                    <CrawlDurationCell crawl={run} />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <TableFrame>
              {/* No heading above it: the table fills the website page's
                  "Indexeringar" tab, so it takes the tab's name. */}
              <Table
                data={sortedData}
                columns={columns}
                idKey="id"
                aria-label={t("crawls")}
                pinnedColumn="started"
                plugins={{ sort: sortPlugin }}
              />
            </TableFrame>
          )}
        </>
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
