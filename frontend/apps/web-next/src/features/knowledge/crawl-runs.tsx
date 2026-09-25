"use client";

import {
  proportional,
  Table,
  useTableSortable,
  useTableSortableState,
  type TableColumn
} from "@astryxdesign/core/Table";
import { SearchX } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { formatDateTime, formatDuration, formatRelativeTime } from "@/lib/format";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import type { CrawlRun } from "./knowledge";
import {
  CRAWL_RUN_COMPARATORS,
  CRAWL_RUN_DEFAULT_SORT,
  type CrawlRunSortKey
} from "./knowledge-sort";
import { filterCrawlRuns } from "./table-controls";
import { KnowledgeTableControls } from "./table-controls-ui";
import { crawlRunStatus, isSkippedCrawl } from "./website-status";
import { KnowledgeLabel } from "./websites";

type Translate = (key: string, params?: Record<string, string>) => string;

const FAILURE_REASON_KEYS = [
  "EMPTY_CONTENT",
  "NO_CHUNKS",
  "EMBEDDING_TIMEOUT",
  "EMBEDDING_ERROR",
  "DB_ERROR",
  "NO_EMBEDDING_MODEL",
  "MISSING_PROVIDER"
];

function failureTooltip(crawl: CrawlRun, t: Translate): string | undefined {
  const summary = crawl.failure_summary;
  if (!summary || Object.keys(summary).length === 0) return undefined;
  const lines = Object.entries(summary)
    .map(([reason, count]) => {
      const label = FAILURE_REASON_KEYS.includes(reason) ? t(`failure_reason_${reason}`) : reason;
      return `${label}: ${count}`;
    })
    .join("\n");
  return `${t("failure_reasons_tooltip")}:\n${lines}`;
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
      tooltip={detail}
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
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <KnowledgeLabel
        tone="accent"
        label={
          files > 0
            ? t("crawled_pages_and_files", { pages: String(pages), files: String(files) })
            : t("crawled_pages", { count: String(pages) })
        }
      />
      {(successPages > 0 || successFiles > 0) && (
        <KnowledgeLabel
          tone="success"
          label={
            successPages > 0 && successFiles > 0
              ? t("pages_and_files_succeeded", {
                  pages: String(successPages),
                  files: String(successFiles)
                })
              : successPages > 0
                ? t("pages_succeeded", { count: String(successPages) })
                : t("files_succeeded", { count: String(successFiles) })
          }
        />
      )}
      {(pagesFailed > 0 || filesFailed > 0) && (
        <KnowledgeLabel
          tone="error"
          label={
            pagesFailed > 0 && filesFailed > 0
              ? t("pages_and_files_failed", {
                  pages: String(pagesFailed),
                  files: String(filesFailed)
                })
              : pagesFailed > 0
                ? t("pages_failed", { count: String(pagesFailed) })
                : t("files_failed", { count: String(filesFailed) })
          }
          tooltip={failureTooltip(crawl, t)}
        />
      )}
    </div>
  );
}

/**
 * A website's crawl history: a filter box and a bordered Astryx table that
 * sorts by its column headers, newest crawl first.
 */
export function CrawlRunsTable({ runs }: { runs: CrawlRun[] }) {
  const t = useTranslations();
  const locale = useLocale();
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
      renderCell: (run) => (
        <span className="font-mono text-sm">{formatDateTime(run.created_at)}</span>
      )
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
      renderCell: (run) =>
        run.finished_at && run.created_at
          ? formatDuration(run.created_at, run.finished_at)
          : run.created_at
            ? t("started_time_ago", { timeAgo: formatRelativeTime(run.created_at, locale) })
            : "—"
    }
  ];

  return (
    <div className="flex flex-col gap-4">
      <KnowledgeTableControls
        filterValue={filter}
        onFilterChange={setFilter}
        filterLabel={t("fix_crawls_filter_label")}
        filterPlaceholder={t("ui_filter_items", { resourceName: t("resource_crawls") })}
      />
      {sortedData.length === 0 ? (
        <EmptyState
          icon={<SearchX />}
          title={t("ui_no_items_matching", { resourceNamePlural: t("resource_crawls") })}
          isCompact
        />
      ) : (
        <SpaceTableFrame>
          <Table data={sortedData} columns={columns} idKey="id" plugins={{ sort: sortPlugin }} />
        </SpaceTableFrame>
      )}
    </div>
  );
}
