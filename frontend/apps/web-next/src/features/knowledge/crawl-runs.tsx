"use client";

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
import { EmptyState } from "@/components/composites/empty-state";
import { formatDuration } from "@/lib/format";
import { ClientTime } from "@/components/composites/client-time";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import type { CrawlRun } from "./knowledge";
import {
  CRAWL_RUN_COMPARATORS,
  CRAWL_RUN_DEFAULT_SORT,
  type CrawlRunSortKey
} from "./knowledge-sort";
import { filterCrawlRuns } from "./table-controls";
import { KnowledgeLabel, KnowledgeTableControls } from "./table-controls-ui";
import { crawlRunStatus, isSkippedCrawl, pagesAndFilesText } from "./website-status";

type Translate = (key: string, values?: Record<string, string | number>) => string;

const FAILURE_REASON_KEYS = [
  "EMPTY_CONTENT",
  "NO_CHUNKS",
  "EMBEDDING_TIMEOUT",
  "EMBEDDING_ERROR",
  "DB_ERROR",
  "NO_EMBEDDING_MODEL",
  "MISSING_PROVIDER"
];

/** Why pages or files failed, per reason: "Tomma sidor: 2, Ingen indexerbar text: 1". */
function failureBreakdown(crawl: CrawlRun, t: Translate): string | undefined {
  const summary = crawl.failure_summary;
  if (!summary || Object.keys(summary).length === 0) return undefined;
  return Object.entries(summary)
    .map(([reason, count]) => {
      const label = FAILURE_REASON_KEYS.includes(reason) ? t(`failure_reason_${reason}`) : reason;
      return `${label}: ${count}`;
    })
    .join(", ");
}

/** The run's state as a status dot and text, with the reason it was skipped or failed. */
function CrawlStatusCell({ crawl }: { crawl: CrawlRun }) {
  const t = useTranslations();
  const status = crawlRunStatus(crawl);
  const detail = isSkippedCrawl(crawl)
    ? t("crawl_skipped_duplicate")
    : status.tone === "error"
      ? (crawl.result_location ?? undefined)
      : undefined;
  return (
    <KnowledgeLabel
      tone={status.tone}
      label={t(status.labelKey)}
      detail={detail}
      isPulsing={status.isPulsing}
    />
  );
}

/** What the run fetched and how much of it succeeded, ported from CrawlResultCell.svelte. */
function CrawlResultCell({ crawl }: { crawl: CrawlRun }) {
  const t = useTranslations();
  if (crawl.status !== "complete") return <span className="text-ax-text-secondary">—</span>;

  const pages = crawl.pages_crawled ?? 0;
  const files = crawl.files_downloaded ?? 0;
  const pagesFailed = crawl.pages_failed ?? 0;
  const filesFailed = crawl.files_failed ?? 0;
  const successPages = pages - pagesFailed;
  const successFiles = files - filesFailed;

  return (
    <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
      <KnowledgeLabel
        tone="accent"
        label={t("space_crawl_crawled", { items: pagesAndFilesText(t, pages, files) })}
      />
      {successPages > 0 || successFiles > 0 ? (
        <KnowledgeLabel
          tone="success"
          label={t("space_crawl_succeeded", {
            items: pagesAndFilesText(t, Math.max(0, successPages), Math.max(0, successFiles))
          })}
        />
      ) : null}
      {pagesFailed > 0 || filesFailed > 0 ? (
        <KnowledgeLabel
          tone="error"
          label={t("space_crawl_failed", { items: pagesAndFilesText(t, pagesFailed, filesFailed) })}
          detail={failureBreakdown(crawl, t)}
        />
      ) : null}
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
 * sorts by its column headers, newest crawl first.
 */
export function CrawlRunsTable({ runs }: { runs: CrawlRun[] }) {
  const t = useTranslations();
  const [filter, setFilter] = useState("");
  const { sortedData, sortConfig } = useTableSortableState<CrawlRun, CrawlRunSortKey>({
    data: filterCrawlRuns(runs, filter),
    defaultSort: CRAWL_RUN_DEFAULT_SORT,
    comparators: CRAWL_RUN_COMPARATORS
  });
  const sortPlugin = useTableSortable<CrawlRun, CrawlRunSortKey>(sortConfig);

  if (runs.length === 0) {
    return <EmptyState title={t("this_website_not_crawled_before")} />;
  }

  const columns: TableColumn<CrawlRun>[] = [
    {
      key: "started",
      header: t("fix_crawl_started_column"),
      width: proportional(1),
      sortable: true,
      renderCell: (run) =>
        run.created_at ? <ClientTime value={run.created_at} format="date_time" /> : "—"
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      sortable: true,
      renderCell: (run) => <CrawlStatusCell crawl={run} />
    },
    {
      key: "results",
      header: t("results"),
      width: proportional(2),
      sortable: true,
      renderCell: (run) => <CrawlResultCell crawl={run} />
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
    </div>
  );
}
